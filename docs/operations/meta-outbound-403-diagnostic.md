# Diagnóstico do outbound Meta `(#131005) Access denied`

Data da análise: 2026-09-09. Escopo: investigação estática do código e correlação
com os logs fornecidos para o envio ao `phone_number_id=876969468828520`. Nenhuma
alteração foi feita no Runtime V2, no fluxo ou no Google Calendar.

## Sumário executivo

O restart está correto: a sessão nova, a execução do start node
`fb2ce735-69f2-4836-aebc-5b280ee793e8` e o avanço ao Choice
`8dc1712f-d493-49da-9bc1-5171fbb455c8` antecedem o problema. O erro acontece depois
do Runtime, no worker outbound, quando a Meta rejeita o `POST
/{phone_number_id}/messages` com HTTP 403 e código `131005`.

A causa raiz **confirmada até o limite das evidências disponíveis** é uma quebra de
autorização entre o token armazenado no provider ativo e o asset
`phone_number_id=876969468828520`. `connected`, `is_active=true` e a existência de
token são estados locais; não são prova de que a Meta ainda concede ao sujeito do
token `whatsapp_business_messaging` sobre esse número.

Não há acesso ao banco/logs do ambiente nem um token mascarado utilizável neste
checkout. Portanto não é possível, apenas pelo repositório, escolher com honestidade
entre estas causas Meta equivalentes: scope ausente; token revogado/expirado; token
emitido por outro app/business; system user sem o asset; WABA/número removido ou não
atribuído. A hipótese mais forte para este incidente é **provider/token antigo ou
manual incompatível com o número**, especialmente se houve reconexão: o callback de
Embedded Signup preserva providers manuais e não os desativa, enquanto o worker
escolhe o provider Meta ativo mais recentemente atualizado. A confirmação final
requer executar os checks Graph descritos abaixo com o token efetivamente selecionado.

## 1. Provider e origem exata do token no worker

O `send_worker` não confia no `provider_id` contido no payload para selecionar a
credencial. Ele chama `resolve_active_meta_provider_credentials` pelo `tenant_id`.
Esse resolver:

1. consulta todos os registros `tenant_whatsapp_providers` do tenant com
   `provider_type=meta_cloud`;
2. ordena por `is_active DESC, updated_at DESC`;
3. escolhe o primeiro provider ativo;
4. descriptografa `access_token_encrypted` desse registro;
5. devolve, do **mesmo registro**, token, `phone_number_id`, `waba_id` e
   `business_id`.

Só se nenhum provider ativo com token e número for resolvido o worker cai no caminho
legado (`get_tenant_whatsapp_credentials`). Pelos logs informados (`provider
status=connected`, `is_active=true`, e os campos de provider), o caminho provável é
`source=provider`, não o legado. O log `[META TOKEN SOURCE]` e o campo
`provider_source` de `[FLOW MESSAGE PROVIDER]` são a evidência definitiva para cada
job.

O token nunca deve ser registrado. O worker já calcula SHA-256 e registra somente os
16 primeiros caracteres (`token_hash`) e o comprimento. Esses dois valores permitem
comparar jobs/reconexões sem expor a credencial.

### Como o token chega ao banco

Há duas origens possíveis no modelo:

- **Embedded Signup** (`auth_type=embedded_signup`): o callback troca o `code` usando
  `META_APP_ID`/`META_APP_SECRET`, descobre business, WABA e o primeiro telefone
  retornados pela Graph API, e grava o token criptografado junto com esses IDs.
- **Manual** (`auth_type=manual`): o token e os IDs vêm do formulário/API de provider
  e são criptografados no save.

Uma reconexão Embedded Signup atualiza apenas um provider que já seja
`embedded_signup`. Desde a mudança que separou `auth_type`, uma conexão manual é
preservada e não é desativada automaticamente. Assim, uma reconexão recente pode
criar/atualizar um provider Embedded sem torná-lo o único ativo. O resolver não
verifica `auth_type`, `status=connected`, app emissor, WABA ownership nem permissões;
se houver mais de um ativo, ganha o de `updated_at` mais recente.

## 2. Relação token, app, business, WABA e telefone

O registro local mantém `app_id`, `business_id`, `business_manager_id`, `waba_id` e
`phone_number_id`, mas o envio usa apenas o token descriptografado e
`phone_number_id`. Os demais IDs são diagnósticos; nenhuma validação pré-send prova
que pertencem à mesma cadeia de autorização.

Para o POST de mensagens, o token precisa:

- ter sido emitido pelo app correto e continuar válido/não revogado;
- incluir `whatsapp_business_messaging`;
- pertencer a um usuário/system user com acesso ao WABA e ao phone asset;
- autorizar especificamente `876969468828520` no mesmo business/WABA;
- estar associado a um app ainda instalado/autorizado para esse business.

`whatsapp_business_management` é necessário para descoberta/administração dos assets
usada pelo onboarding e pelos checks de WABA; não substitui
`whatsapp_business_messaging`, que é a permissão crítica para enviar. O Wazza pede os
dois scopes no Embedded Signup atual. Isso não corrige tokens emitidos antes dessa
configuração nem prova que a concessão/atribuição de assets persistiu.

### Confirmação operacional, sem exibir o token

Executar para o **provider_id mostrado no job que falhou**, mantendo respostas em
log restrito e sem o access token:

1. consultar `/debug_token?input_token=<token>` usando app access token e conferir
   `is_valid`, `app_id`, `expires_at`, `data_access_expires_at`, usuário e scopes;
2. consultar `/me?fields=id,name` com o token selecionado;
3. consultar `/876969468828520?fields=id,verified_name,display_phone_number,status`;
4. consultar `/<waba_id>/phone_numbers` e provar que a lista contém
   `876969468828520`;
5. consultar os assets/usuários atribuídos do business/system user e provar que WABA
   e número estão concedidos;
6. comparar o `app_id` do debug token ao app configurado e `business_id`, `waba_id` e
   telefone retornados pela Meta aos valores do provider;
7. comparar `created_at`, `updated_at`, `auth_type`, `onboarding_source` e o hash
   mascarado entre providers para identificar troca/reconexão.

O endpoint interno de diagnóstico já faz `/me` e
`/{phone_number_id}?fields=verified_name,display_phone_number,quality_rating,status`,
mas ainda não faz `debug_token`, não lista os números da WABA e não comprova scopes
ou asset assignment. Logo um resultado local `connected` não fecha o diagnóstico.

## 3. Onde o `131005` é recebido

O fluxo técnico é:

1. Runtime V2 produz uma `SendMessageAction` já renderizada;
2. o channel adapter apenas publica o payload no RQ;
3. `send_worker.send_whatsapp_message` resolve novamente o provider ativo;
4. `send_text_message_via_meta` cria o payload e chama
   `MetaCloudClient.post('/876969468828520/messages')`;
5. `MetaCloudClient` envia Bearer token para Graph API v23.0;
6. ao receber HTTP 403, `_raise_api_error` preserva o payload Meta no
   `MetaApiError`, mascara a mensagem para “Permissão negada...” e o worker registra
   `reason=meta_api_error` e relança a exceção.

Portanto `131005` é uma resposta da Meta no limite HTTP outbound. Não é erro do
restart nem falha de transição do Runtime V2. O código só marca provider como
`token_expired` automaticamente em HTTP 401; um 403 permanece localmente
`connected`, explicando o estado contraditório observado.

## 4. Ordem, falha e `sequence_number`

O Runtime executa nós e acumula ações antes do envio. Depois, o runtime worker usa
uma list comprehension que despacha cada ação para a fila. “Queued” significa apenas
publicado no RQ; não espera a resposta da Meta. Assim o avanço ao Choice e seu enqueue
não dependem do sucesso remoto da mensagem do start.

Há um lock Redis por `tenant_id + telefone`, portanto dois jobs não fazem o POST
simultaneamente. Isso oferece exclusão mútua, **não ordem FIFO transacional**: workers
concorrentes disputam o lock, retries podem voltar depois e o lock é liberado quando
o primeiro envio falha. O próximo job pode então enviar normalmente. Não há cadeia
de dependência RQ (`depends_on`) nem cancelamento dos outbounds seguintes.

Existe suporte parcial a `sequence_number` no worker. Quando presente, ele lê o
último número enviado do Redis, descarta apenas sequências menores e grava o novo
valor somente após sucesso. Ele não espera por gaps, não bloqueia uma sequência maior
quando a menor falha e aceita números iguais. Portanto nem mesmo preencher o campo,
isoladamente, implementaria “falha anterior bloqueia próxima mensagem”.

No caminho Runtime V2 analisado, `_enqueue_whatsapp_text` não inclui
`sequence_number` no payload. O adapter também não o sintetiza; a normalização da
fila só repassa o campo se o produtor o fornecer. Por isso start e Choice chegam com
`sequence_number=None`. Há gerador `_next_flow_sequence` em caminhos do engine
legado, mas ele não é usado pelo produtor Runtime V2.

Decisão de produto recomendada: mensagens que fazem parte do mesmo batch/turno devem
ser tratadas como uma sequência causal; se a primeira falhar definitivamente, as
seguintes não devem ser enviadas fora de contexto. A implementação futura deve usar
ordem durável por sessão/conversa e dependências/estado (`pending`, `sent`, `failed`,
`blocked`), não apenas o contador Redis atual. Isso é uma recomendação separada; não
foi alterado o Runtime nem a fila nesta análise.

## 5. Diagnóstico separado de `nome_clinica`

`{{nome_clinica}}` não é uma variável builtin do `FlowRenderContext`. O contexto
expõe metadados seguros (`tenant_id`, contato, conversa, lead, datas, flow e session),
mais `session.variables` e outputs de nós. Ele não carrega o objeto `Tenant` nem cria
um alias `nome_clinica` a partir de `Tenant.name`.

Como a sessão reiniciada tem `variables={}`, o placeholder não tem fonte e aparece em
`missing_keys=['nome_clinica']`; a política padrão transforma a variável ausente em
string vazia, produzindo “Clínica .”. No desenho atual, ela deveria vir de uma
variável persistida em `session.variables` (por exemplo, inicializada antes da
mensagem) ou de um futuro campo seguro explícito do tenant no render context. Qual
dessas fontes é a regra de negócio correta precisa ser decidida separadamente. Não há
relação causal com o HTTP 403 e nada foi corrigido aqui.

## 6. Recomendação mínima

1. Identificar nos logs o `provider_id`, `provider_source`, `auth_type`,
   `updated_at`, `waba_id`, `business_id`, `phone_number_id` e `token_hash` do job
   `b893fe94-468c-4cb1-b6b8-419f16943b1d`.
2. Rodar `debug_token` e os checks de asset acima para esse mesmo token/provider.
3. Se scope/asset/app não bater, reatribuir WABA e número ao system user ou refazer o
   Embedded Signup no app/business corretos; depois tornar **somente esse provider**
   ativo. Não basta editar o status para `connected`.
4. Revalidar com um POST controlado usando `876969468828520` e só então considerar a
   conexão saudável.
5. Em melhoria posterior e independente, fazer 403 de autorização degradar o status
   do provider e ampliar o health check para scopes + WABA + phone asset.

Com as evidências atuais, a correção mínima não envolve Runtime V2, fluxo ou Calendar:
é corrigir/reautorizar a credencial e a atribuição Meta do provider efetivamente
selecionado pelo send worker.
