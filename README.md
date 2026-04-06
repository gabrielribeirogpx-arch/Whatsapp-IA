# WhatsApp IA SaaS

Sistema profissional de atendimento WhatsApp com IA + humano + painel web estilo WhatsApp.

## Stack
- **Backend:** FastAPI + SQLAlchemy + SSE
- **Frontend:** Next.js 14 (App Router)
- **Banco padrão:** SQLite (pode usar `DATABASE_URL` no Railway/PostgreSQL)

## Variáveis de ambiente
Backend:
- `VERIFY_TOKEN`
- `WHATSAPP_TOKEN`
- `PHONE_NUMBER_ID`
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (opcional, padrão: `gpt-4o-mini`)
- `DATABASE_URL` (opcional)

Frontend:
- `NEXT_PUBLIC_API_URL` (ex: `http://localhost:8000`)

## Fluxo principal
1. `POST /webhook` recebe mensagem da Meta.
2. Mensagem é salva em `messages` e a conversa em `conversations` é atualizada.
3. Se `conversation.status == "bot"`, a IA responde usando histórico recente da conversa.
4. Resposta é enviada via WhatsApp Cloud API e também salva no banco.
5. Se `conversation.status == "human"`, a IA é pausada.

## Endpoints principais
- `GET /webhook` verificação Meta
- `POST /webhook`
- `GET /api/conversations`
- `GET /api/messages/{phone}`
- `POST /api/send-message`
- `POST /api/take-over/{phone}` (alterna `bot`/`human`)
- `GET /api/stream/messages/{phone}` (SSE)

## Rodando localmente
### Backend
```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Acesse:
- `http://localhost:3000/dashboard`
- `http://localhost:3000/chat`
