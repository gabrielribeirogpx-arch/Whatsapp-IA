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
- `TURNSTILE_SECRET_KEY` (obrigatório em produção/staging para validar Cloudflare Turnstile)
- `TURNSTILE_ENABLED` (opcional; padrão `true`)
- `TURNSTILE_DISABLED` (opcional; use apenas localmente/em testes controlados)
- `TURNSTILE_DEV_BYPASS` (opcional; permite o token local de desenvolvimento fora de produção)

Frontend:
- `NEXT_PUBLIC_API_URL` (ex: `http://localhost:8000`)
- `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (chave pública do widget Cloudflare Turnstile)


## Railway Deployment Notes

O deploy do backend no Railway depende da instalação do runtime Python pelo Railpack/mise antes da instalação das dependências do projeto. Foi registrado um incidente em que o build falhou nessa etapa inicial com erro semelhante a:

```text
Failed to install core:python@3.11.9:
No GitHub artifact attestations found
```

A causa operacional foi uma incompatibilidade/falha de verificação de GitHub Artifact Attestations no fluxo mise/Railpack para o artefato Python resolvido pelo Railway. Como a falha acontece antes do `pip install`, alterar `requirements.txt` não resolve o problema.

Variável obrigatória nos serviços Python do Railway enquanto esse comportamento puder ocorrer:

```env
MISE_PYTHON_GITHUB_ATTESTATIONS=false
```

Impacto esperado:
- estabiliza a instalação do runtime Python no Railway/Railpack;
- permite que o build avance para instalação de dependências e start da aplicação;
- não altera versão Python, dependências nem pipeline funcional da aplicação;
- deve ser mantida como dependência operacional documentada até validação segura de remoção em staging.

### Python runtime atual

A versão Python versionada no repositório está em `runtime.txt` como `python-3.11`. Não existem atualmente `.python-version`, `mise.toml`, `railpack-plan.json` ou `nixpacks.toml` versionados no repositório. No incidente observado, o Railway/Railpack resolveu esse runtime para `core:python@3.11.9` via mise.

### Known Railway Issues

- **GitHub Attestations no mise/Railpack:** se o build falhar com `No GitHub artifact attestations found`, confirmar `MISE_PYTHON_GITHUB_ATTESTATIONS=false` nos serviços Python e redeployar.
- **Build cache:** se o erro persistir após corrigir variáveis, executar redeploy com cache limpo e confirmar que o commit e o ambiente Railway corretos estão selecionados.
- **Imports case-sensitive no Linux:** Railway executa em Linux; imports devem respeitar exatamente maiúsculas/minúsculas dos nomes de arquivos.
- **Deploy troubleshooting:** identificar primeiro se a falha ocorre na instalação do runtime, instalação de dependências, migrations/start do backend, worker ou build do frontend.

Para detalhes operacionais, variáveis críticas, serviços Railway, Postgres, Redis, worker, backend e frontend, consulte `docs/infrastructure/railway.md`.

## Proteção anti-bot (Cloudflare Turnstile)
Os fluxos públicos de maior risco (`/login`, `/register` e `/forgot-password`) usam Cloudflare Turnstile no frontend e validação server-side no backend antes de consultar/criar credenciais. A API também aplica rate limit básico em memória por IP e por hash de email para reduzir brute force, spam e enumeração.

### Setup produção/staging
1. Crie um widget no Cloudflare Turnstile para os domínios públicos do Wazza API.
2. Configure no frontend `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.
3. Configure no backend `TURNSTILE_SECRET_KEY` e mantenha `TURNSTILE_ENABLED=true` em staging/produção.
4. Monitore os logs `[TURNSTILE VALIDATION SUCCESS]` e `[TURNSTILE VALIDATION FAILED]`; tokens nunca são logados.

### Fallback de desenvolvimento
Em desenvolvimento local, quando `NEXT_PUBLIC_TURNSTILE_SITE_KEY` e `TURNSTILE_SECRET_KEY` não estão configurados, o frontend emite um token local (`dev-turnstile-token`) e o backend aceita esse token em `localhost`/`127.0.0.1` ou quando `ENV=development`/`TURNSTILE_DEV_BYPASS=true`. Para testes automatizados, também é possível definir `TURNSTILE_DISABLED=true` em ambiente não público.

### Checklist licitação-ready
- Login, onboarding e recuperação de senha protegidos com Turnstile discreto e responsivo.
- Validação obrigatória no backend, com fail-closed quando a secret não está configurada em produção/staging.
- Rate limit por IP e identificador de email nos endpoints públicos.
- Respostas de login e recuperação mantêm mensagens genéricas para reduzir enumeração.
- Observabilidade padronizada sem exposição de tokens ou secrets.
- Riscos residuais: rate limit em memória deve ser migrado para Redis/WAF em múltiplas réplicas; validar domínios permitidos no painel Cloudflare e acompanhar falsos positivos em rede móvel/lenta.

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
uvicorn app.main:app --reload --port 8000
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
