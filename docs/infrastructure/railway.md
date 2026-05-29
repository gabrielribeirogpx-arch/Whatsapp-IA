# Railway Infrastructure Notes

Este documento registra decisões operacionais do deploy no Railway para reduzir regressões e tornar a operação mais previsível e auditável.

## Escopo

- Backend FastAPI executado como serviço web.
- Worker Python para processamento assíncrono.
- Frontend Next.js como serviço separado quando publicado no Railway.
- Postgres gerenciado pelo Railway via `DATABASE_URL`.
- Redis gerenciado pelo Railway via `REDIS_URL` para filas/worker.

## Build pipeline atual

O repositório contém configurações explícitas e implícitas usadas pelo Railway/Railpack:

1. O Railway detecta o runtime a partir dos arquivos do repositório.
2. A versão Python é declarada em `runtime.txt` como `python-3.11`.
3. O serviço web usa o `Procfile`:
   - `web`: entra em `backend`, executa `alembic upgrade head` e inicia `backend/start.sh`.
   - `worker`: executa `python backend/worker_rq.py`.
4. O backend instala dependências Python a partir de `backend/requirements.txt` no pipeline do serviço backend.
5. O frontend instala dependências Node a partir de `frontend/package.json` e `frontend/package-lock.json` no pipeline do serviço frontend.

> Importante: não alterar runtime, versão Python ou pipeline de build sem uma mudança planejada e testada separadamente.

## Mapeamento do versionamento Python

Arquivos investigados para definição do Python:

| Arquivo | Status | Observação |
| --- | --- | --- |
| `runtime.txt` | Presente | Define `python-3.11`. Esta é a declaração atual do runtime Python no repositório. |
| `.python-version` | Ausente | Não há pin local via pyenv/asdf neste repositório. |
| `mise.toml` | Ausente | Não há pin explícito do mise neste repositório. |
| `railpack-plan.json` | Ausente | Não há plano Railpack versionado. |
| `nixpacks.toml` | Ausente | Não há configuração Nixpacks versionada. |
| `.tool-versions` | Ausente | Não há pin asdf/mise alternativo versionado. |

Conclusão operacional: a versão Python versionada no repositório está em `runtime.txt` como `python-3.11`. Durante o deploy, o Railway/Railpack pode resolver esse runtime para uma versão patch específica de Python via mise. No incidente registrado, a resolução tentou instalar `core:python@3.11.9` antes da instalação das dependências.

## Variáveis críticas

### Build e runtime do Railway

| Variável | Serviço | Obrigatória | Descrição |
| --- | --- | --- | --- |
| `MISE_PYTHON_GITHUB_ATTESTATIONS=false` | Backend/Worker Python | Sim no Railway enquanto o incidente persistir | Workaround para falhas de verificação de GitHub Artifact Attestations no mise/Railpack antes da instalação das dependências. |
| `DATABASE_URL` | Backend/Worker | Sim em produção | URL do Postgres gerenciado pelo Railway. |
| `REDIS_URL` | Worker/Backend que usa fila | Sim quando filas estão habilitadas | URL do Redis gerenciado pelo Railway para RQ/filas. |
| `PYTHONPATH` | Backend/Worker | Conforme imagem/pipeline | Deve permitir imports do pacote `backend/app`; no Dockerfile atual é `/app/backend`. |

### Backend/API

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `VERIFY_TOKEN` | Sim | Token de verificação do webhook Meta/WhatsApp. |
| `WHATSAPP_TOKEN` | Conforme tenant/configuração | Token fallback global da WhatsApp Cloud API. |
| `PHONE_NUMBER_ID` | Conforme tenant/configuração | Identificador fallback global do número WhatsApp. |
| `OPENAI_API_KEY` | Sim para IA | Chave de API da OpenAI. |
| `OPENAI_MODEL` | Não | Modelo usado pela IA; padrão documentado no README é `gpt-4o-mini`. |
| `TURNSTILE_SECRET_KEY` | Sim em staging/produção | Secret server-side do Cloudflare Turnstile. |
| `TURNSTILE_ENABLED` | Não | Controla validação Turnstile; padrão esperado `true`. |
| `TURNSTILE_DISABLED` | Não | Somente para local/testes controlados. Não usar em produção. |
| `TURNSTILE_DEV_BYPASS` | Não | Somente para desenvolvimento local/controlado. |

### Frontend

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | Sim | URL pública do backend consumida pelo frontend. |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Sim em staging/produção | Chave pública do widget Cloudflare Turnstile. |

## Railway services

### Backend

Responsável pela API FastAPI, webhooks da Meta/WhatsApp, autenticação de tenant, SSE e orquestração de IA.

- Start atual pelo `Procfile`: `cd backend && alembic upgrade head && bash start.sh`.
- Executa migrations Alembic antes de subir a aplicação.
- Depende de Postgres (`DATABASE_URL`) em produção.
- Deve receber `MISE_PYTHON_GITHUB_ATTESTATIONS=false` no Railway enquanto o problema de attestation do mise/Railpack puder ocorrer.

### Worker

Responsável por tarefas assíncronas e filas RQ.

- Start atual pelo `Procfile`: `python backend/worker_rq.py`.
- Depende de Redis (`REDIS_URL`) quando filas estão habilitadas.
- Deve usar a mesma versão Python efetiva do backend.
- Deve receber as mesmas variáveis críticas de integração necessárias para processar tarefas com segurança.

### Frontend

Responsável pela interface Next.js.

- Código em `frontend/`.
- Depende de `NEXT_PUBLIC_API_URL` apontando para o backend correto por ambiente.
- Depende de `NEXT_PUBLIC_TURNSTILE_SITE_KEY` em staging/produção.

### Postgres

Banco relacional de produção.

- Deve ser provisionado como serviço Railway Postgres ou equivalente.
- O backend usa `DATABASE_URL` para conexão.
- Migrations são aplicadas no start do serviço web via Alembic.
- Antes de alterações de schema, validar rollback, backup e compatibilidade com dados existentes.

### Redis

Cache/fila para worker RQ.

- Deve ser provisionado como serviço Railway Redis ou equivalente.
- Worker usa `REDIS_URL`.
- Se o Redis estiver indisponível, tarefas assíncronas podem ficar paradas ou falhar; monitorar logs do worker.

## Railway Deployment Notes

As notas abaixo descrevem o workaround operacional obrigatório para deploys Python no Railway enquanto houver risco de falha de attestation no mise/Railpack.

## Workaround Railway/Mise

### Erro observado

Durante o deploy do backend, o build falhou antes da instalação das dependências Python com erro semelhante a:

```text
Failed to install core:python@3.11.9:
No GitHub artifact attestations found
```

### Causa operacional

O Railway/Railpack usa mise para instalar runtimes. Em versões recentes, a verificação de GitHub Artifact Attestations pode falhar para determinados artefatos Python resolvidos pelo mise. Quando isso ocorre, o build interrompe antes do `pip install`, portanto alterações em dependências Python não corrigem o incidente.

### Variável necessária

Configurar nos serviços Python do Railway:

```env
MISE_PYTHON_GITHUB_ATTESTATIONS=false
```

### Impacto

- O deploy volta a instalar o Python e prossegue para as etapas de dependências e start.
- A mudança atua apenas no comportamento de verificação de attestation do mise para Python.
- Não altera a versão Python declarada, dependências, código da aplicação ou pipeline funcional.
- Deve ser tratada como dependência operacional do ambiente Railway até que o problema seja resolvido upstream e validado em staging.

## Known Railway Issues

### GitHub Attestations no mise/Railpack

Sintoma:

```text
Failed to install core:python@3.11.9:
No GitHub artifact attestations found
```

Ação:

1. Confirmar se `MISE_PYTHON_GITHUB_ATTESTATIONS=false` está configurada nos serviços Python.
2. Redeployar sem alterar runtime.
3. Se necessário, limpar cache do build e redeployar.
4. Registrar data, serviço afetado e hash do commit do incidente.

### Build cache

Sintomas comuns:

- Deploy usa dependências antigas.
- Build continua falhando mesmo após variável corrigida.
- Artefatos gerados parecem incompatíveis com o commit atual.

Ações:

1. Executar redeploy com cache limpo no Railway.
2. Confirmar que o commit correto está selecionado.
3. Confirmar que variáveis foram salvas no ambiente correto.
4. Evitar mudanças simultâneas de runtime e dependências durante a investigação.

### Imports case-sensitive no Linux

O ambiente Linux do Railway diferencia maiúsculas/minúsculas em caminhos e nomes de arquivos.

Ações:

1. Verificar se imports batem exatamente com o nome dos arquivos.
2. Evitar renomes que só mudam capitalização sem validação no Git.
3. Rodar testes em ambiente Linux antes de promover para produção.

### Deploy troubleshooting

Checklist rápido:

1. Identificar se a falha ocorre antes ou depois da instalação de dependências.
2. Se falhar durante instalação do runtime Python, verificar `MISE_PYTHON_GITHUB_ATTESTATIONS=false`.
3. Se falhar no `pip install`, revisar `backend/requirements.txt` e logs de resolução de dependências.
4. Se falhar no start, revisar `Procfile`, `backend/start.sh`, `DATABASE_URL` e migrations Alembic.
5. Se falhar no worker, revisar `REDIS_URL`, logs do Redis e import paths.
6. Se falhar no frontend, revisar `frontend/package-lock.json`, `NEXT_PUBLIC_API_URL` e variáveis públicas.

## Regras de mudança

Para manter a operação previsível:

- Não migrar Python sem plano específico de upgrade.
- Não alterar `runtime.txt`, `Procfile`, Dockerfile ou pipeline do Railway junto com mudanças funcionais sem validação em staging.
- Toda nova variável crítica deve ser adicionada a este documento e ao README.
- Mudanças em Postgres, Redis, worker ou frontend devem incluir plano de rollback operacional.
