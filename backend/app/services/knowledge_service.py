import uuid
import ipaddress
import re
import socket
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeBase, KnowledgeChunk
from backend.app.services.embedding_service import cosine_similarity, generate_embedding

SIMILARITY_THRESHOLD = 0.2
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
DEFAULT_HTTP_TIMEOUT = 8
MAX_CRAWL_PAGES = 10
MAX_CRAWL_DEPTH = 2
MAX_PAGE_BYTES = 1_500_000
MIN_RELEVANT_TEXT_LENGTH = 80

BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "169.254.169.254",
}


@dataclass
class RetrievedKnowledge:
    source: str
    content: str


@dataclass
class CrawlPageResult:
    url: str
    content: str


def create_knowledge_item(db: Session, tenant_id: uuid.UUID, title: str, content: str) -> KnowledgeBase:
    item = KnowledgeBase(
        tenant_id=tenant_id,
        title=title.strip(),
        content=content.strip(),
        embedding=generate_embedding(content),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_knowledge_items(db: Session, tenant_id: uuid.UUID) -> list[KnowledgeBase]:
    return (
        db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.tenant_id == tenant_id)
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        )
        .scalars()
        .all()
    )


def delete_knowledge_item(db: Session, tenant_id: uuid.UUID, knowledge_id: uuid.UUID) -> bool:
    item = (
        db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        .scalars()
        .first()
    )
    if not item:
        return False

    db.delete(item)
    db.commit()
    return True


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    content_parts: list[str] = []
    for page in reader.pages:
        content_parts.append(page.extract_text() or "")
    return clean_text("\n".join(content_parts))


def clean_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return normalized.strip()


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(cleaned):
        chunk = cleaned[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def _is_valid_http_url(raw_url: str) -> bool:
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_blocked_host(hostname: str | None) -> bool:
    if not hostname:
        return True

    host = hostname.lower().strip()
    if host in BLOCKED_HOSTS:
        return True

    if host.endswith(".local"):
        return True

    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            return True
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Se não resolve, não tenta acessar.
        return True

    for info in infos:
        addr = info[4][0]
        if addr in BLOCKED_HOSTS:
            return True
        try:
            ip_obj = ipaddress.ip_address(addr)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                return True
        except ValueError:
            continue

    return False


def validate_crawl_url(raw_url: str) -> str:
    normalized = (raw_url or "").strip()
    if not _is_valid_http_url(normalized):
        raise ValueError("URL inválida. Use http:// ou https://")

    parsed = urlparse(normalized)
    if _is_blocked_host(parsed.hostname):
        raise ValueError("Domínio não permitido para crawl")

    return normalized


def extract_page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = clean_text(soup.get_text(separator=" "))
    if len(text) < MIN_RELEVANT_TEXT_LENGTH:
        return ""
    return text


def _extract_internal_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).hostname
    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(base_url, anchor["href"])
        parsed = urlparse(candidate)

        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.hostname != base_host:
            continue
        if parsed.fragment:
            candidate = candidate.split("#", 1)[0]

        normalized = candidate.rstrip("/")
        if normalized in seen:
            continue

        seen.add(normalized)
        links.append(normalized)

    return links


def crawl(url: str, depth: int = 1, max_pages: int = MAX_CRAWL_PAGES) -> list[CrawlPageResult]:
    start_url = validate_crawl_url(url)
    allowed_depth = max(1, min(depth, MAX_CRAWL_DEPTH))
    max_allowed_pages = max(1, min(max_pages, MAX_CRAWL_PAGES))

    queue = deque([(start_url.rstrip("/"), 0)])
    visited: set[str] = set()
    results: list[CrawlPageResult] = []

    headers = {"User-Agent": "Whatsapp-IA-Crawler/1.0"}

    while queue and len(results) < max_allowed_pages:
        current_url, current_depth = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            response = requests.get(
                current_url,
                timeout=DEFAULT_HTTP_TIMEOUT,
                headers=headers,
                allow_redirects=True,
                stream=True,
            )
            response.raise_for_status()
        except requests.RequestException:
            continue

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            response.close()
            continue

        page_bytes = b""
        too_large = False
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            page_bytes += chunk
            if len(page_bytes) > MAX_PAGE_BYTES:
                too_large = True
                break

        response.close()
        if too_large:
            continue

        try:
            html = page_bytes.decode(response.encoding or "utf-8", errors="ignore")
        except LookupError:
            html = page_bytes.decode("utf-8", errors="ignore")

        cleaned = extract_page_text(html)
        if cleaned:
            results.append(CrawlPageResult(url=current_url, content=cleaned))

        if current_depth >= allowed_depth:
            continue

        for link in _extract_internal_links(current_url, html):
            if link in visited:
                continue
            queue.append((link, current_depth + 1))

    return results


def process_pdf_knowledge(db: Session, tenant_id: uuid.UUID, source: str, pdf_bytes: bytes) -> int:
    pdf_text = extract_pdf_text(pdf_bytes)
    chunks = split_text_into_chunks(pdf_text)
    if not chunks:
        return 0

    created = 0
    for chunk in chunks:
        db.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                source=source,
                content=chunk,
                embedding=generate_embedding(chunk),
            )
        )
        created += 1

    db.commit()
    return created


def process_site_knowledge(
    db: Session,
    tenant_id: uuid.UUID,
    url: str,
    depth: int = 1,
    max_pages: int = MAX_CRAWL_PAGES,
) -> tuple[int, int]:
    pages = crawl(url=url, depth=depth, max_pages=max_pages)
    if not pages:
        return (0, 0)

    created_chunks = 0
    for page in pages:
        chunks = split_text_into_chunks(page.content)
        for chunk in chunks:
            db.add(
                KnowledgeChunk(
                    tenant_id=tenant_id,
                    source=page.url,
                    content=chunk,
                    embedding=generate_embedding(chunk),
                )
            )
            created_chunks += 1

    if created_chunks:
        db.commit()

    return (len(pages), created_chunks)


def search_relevant_knowledge(db: Session, tenant_id: uuid.UUID, query_text: str, top_k: int = 5) -> list[RetrievedKnowledge]:
    query_embedding = generate_embedding(query_text)
    if not query_embedding:
        return []

    chunk_items = (
        db.execute(select(KnowledgeChunk).where(KnowledgeChunk.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    ranked_chunks = sorted(chunk_items, key=lambda item: cosine_similarity(item.embedding, query_embedding), reverse=True)

    relevant: list[RetrievedKnowledge] = []
    for item in ranked_chunks:
        score = cosine_similarity(item.embedding, query_embedding)
        if score < SIMILARITY_THRESHOLD:
            continue
        relevant.append(RetrievedKnowledge(source=item.source, content=item.content))
        if len(relevant) >= top_k:
            break

    if len(relevant) < top_k:
        legacy_items = (
            db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        ranked_legacy = sorted(legacy_items, key=lambda item: cosine_similarity(item.embedding, query_embedding), reverse=True)
        for item in ranked_legacy:
            score = cosine_similarity(item.embedding, query_embedding)
            if score < SIMILARITY_THRESHOLD:
                continue
            relevant.append(RetrievedKnowledge(source=item.title, content=item.content))
            if len(relevant) >= top_k:
                break
    return relevant


def build_rag_context(query_text: str, items: list[RetrievedKnowledge]) -> str:
    if not items:
        return query_text

    context_lines = ["Use essas informações do site:"]
    for index, item in enumerate(items, start=1):
        context_lines.extend(
            [
                "",
                f"[CHUNK {index} - {item.source}]",
                item.content,
            ]
        )
    context_lines.extend(
        [
            "",
            f"Pergunta do cliente: {query_text}",
        ]
    )
    return "\n".join(context_lines)
