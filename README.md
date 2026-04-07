# WhatsApp IA SaaS Multi-tenant

Sistema SaaS de atendimento WhatsApp com IA + humano + painel web estilo WhatsApp, com isolamento por tenant.

## Stack
- **Backend:** FastAPI + SQLAlchemy + SSE
- **Frontend:** Next.js 14 (App Router)
- **Banco padrão:** SQLite (pode usar `DATABASE_URL` no Railway/PostgreSQL)

## Funcionalidades SaaS
- Multi-tenant com tabela `tenants` e identificação automática por `phone_number_id` no webhook.
- Persistência estruturada em `messages`, `conversations` e `ai_config` por tenant.
- IA contextual com histórico da conversa e prompt personalizado por tenant.
- Painel com login por tenant (slug + senha), inbox tipo WhatsApp e takeover humano/bot.
- Controle de plano com limite mensal de uso e bloqueio.

## Variáveis de ambiente
Backend:
- `VERIFY_TOKEN`
- `WHATSAPP_TOKEN` (fallback global opcional)
- `PHONE_NUMBER_ID` (fallback global opcional)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (opcional, padrão: `gpt-4o-mini`)
- `DATABASE_URL` (opcional)

Frontend:
- `NEXT_PUBLIC_API_URL` (ex: `http://localhost:8000`)

## Fluxo principal (Webhook)
1. `POST /webhook` recebe mensagem da Meta.
2. Extrai `metadata.phone_number_id`, resolve o tenant, salva inbound em `messages`.
3. Atualiza `conversations` do tenant.
4. Se `status == bot` e tenant dentro do plano, IA responde com prompt configurado em `ai_config` + histórico.
5. Envia resposta pela WhatsApp Cloud API do tenant e salva outbound no banco.

## Endpoints principais
- `GET /webhook` verificação Meta
- `POST /webhook`
- `POST /api/auth/login`
- `GET /api/conversations` (headers `X-Tenant-Slug` e `X-Tenant-Password`)
- `GET /api/messages/{phone}` (headers `X-Tenant-Slug` e `X-Tenant-Password`)
- `POST /api/send-message` (headers `X-Tenant-Slug` e `X-Tenant-Password`)
- `POST /api/take-over/{phone}`
- `GET /api/stream/messages/{phone}` (também aceita `tenant_slug` + `tenant_password` por query)

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

## Tenant default de bootstrap
Ao iniciar com banco vazio, é criado automaticamente:
- `slug`: `default`
- `password`: `admin123`
- `phone_number_id`: valor definido em `PHONE_NUMBER_ID` no ambiente
