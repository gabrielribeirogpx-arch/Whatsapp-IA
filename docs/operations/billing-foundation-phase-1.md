# Fundação de planos e entitlements — Fase 1

Esta entrega é somente leitura e não integra Stripe, checkout, cartão, trial automático, cobrança por uso ou enforcement.

## Deploy e validação

1. Publique o código com `BILLING_ENFORCEMENT_ENABLED=false` (valor padrão) e, se desejado, `BILLING_UI_ENABLED=true` (valor padrão).
2. Execute `alembic upgrade head`.
3. Confirme que cada tenant existente possui uma assinatura `legacy` e que `GET /api/billing/current` informa o plano **Acesso legado**.
4. Confirme a área **Plano e cobrança** do hub da conta.
5. Monitore os eventos de auditoria `BILLING_CURRENT_VIEWED` e erros da aplicação antes de qualquer fase de enforcement.

`NULL` em `limit_value` significa explicitamente **ilimitado**. A resolução usa override, não soma: `manual`, `enterprise_contract`, `addon`, `promotion`, `trial`, `plan`, `legacy` (da maior à menor prioridade).

## Rollback

Antes de começar a gravar dados comerciais, o rollback é `alembic downgrade 20260719_wp_auth_type`. Ele remove as quatro tabelas aditivas desta fase. Depois de dados comerciais reais, não faça downgrade destrutivo: mantenha `BILLING_ENFORCEMENT_ENABLED=false`, corrija a aplicação e use uma migration futura de reparo.
