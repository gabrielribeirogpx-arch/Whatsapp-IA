from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product


def get_active_products(db: Session, tenant_id) -> list[Product]:
    products = (
        db.execute(
            select(Product)
            .where(
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
            )
            .order_by(Product.id.asc())
        )
        .scalars()
        .all()
    )
    print(f"[PRODUCTS] total={len(products)} tenant={tenant_id}")
    return products


def build_products_response(products: list[Product]) -> str:
    if not products:
        return "Os planos ainda não foram configurados. Fale com o administrador."

    lines = ["Temos os seguintes planos 👇", ""]
    for product in products:
        name = (product.name or "").strip() or "Plano"
        price = (product.price or "").strip()
        description = (product.description or "").strip()
        title = f"{name} — R${price}" if price else name
        lines.append(title)
        if description:
            lines.append(description)
        lines.append("")

    lines.append("Qual deles faz mais sentido pra você?")
    return "\n".join(lines).strip()
