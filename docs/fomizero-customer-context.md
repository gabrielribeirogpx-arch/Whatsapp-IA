# Identidade de cliente para o MCP do Fomizero

O Wazza deriva a identidade exclusivamente do `RuntimeInput.external_user_id`
criado pelo webhook do WhatsApp. O modelo não fornece telefone, restaurante,
conversa ou cabeçalhos.

Para cada `tools/call`, o cliente envia um contexto JSON canônico, codificado em
base64url, com `iss`, `aud`, `sub`, `cid`, `iat`, `exp`, `rid` e versão. O HMAC
SHA-256 usa a chave derivada do Bearer MCP. A validade padrão é de 60 segundos e
o `rid` precisa coincidir com o identificador JSON-RPC.

Execuções sem um identificador WhatsApp válido continuam aptas a usar recursos
MCP genéricos, mas não enviam contexto de cliente. O Fomizero deve manter
recursos pessoais ocultos quando o contexto verificado estiver ausente.
