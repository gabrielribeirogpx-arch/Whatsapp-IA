# WhatsApp IA SaaS

Sistema completo de atendimento WhatsApp com IA + humano.

## Stack
- **Backend:** FastAPI + SQLAlchemy + SSE
- **Frontend:** Next.js 14 (App Router)
- **Banco padrão:** SQLite (pode usar `DATABASE_URL` no Railway)

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

## Endpoints principais
- `GET /webhook` verificação Meta
- `POST /webhook` recebe mensagens, salva no banco e responde via IA quando `assigned_to == "IA"`
- `GET /api/conversations`
- `GET /api/messages/{phone}`
- `POST /api/send`
- `POST /api/take-over/{phone}`
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
