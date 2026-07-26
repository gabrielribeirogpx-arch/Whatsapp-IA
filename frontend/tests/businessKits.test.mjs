import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const catalog = await readFile(new URL('../components/ai-store/catalog.ts', import.meta.url), 'utf8');
const details = await readFile(new URL('../components/ai-store/AISystemDetailsModal.tsx', import.meta.url), 'utf8');
for (const segment of ['Clínica Odontológica','Clínica Médica','Veterinária','Imobiliária','Advocacia','Restaurante','Pet Shop','Academia','Escola','Hotel','Contabilidade','Oficina','E-commerce','Estética','Salão']) assert.match(catalog, new RegExp(segment), `${segment} is present`);
for (const contract of ['OPERATIONAL_METHODOLOGIES','Sem IA','Híbrida','IA Completa','knowledge_bases','pipelines','custom_fields','dashboards','academy','post_install_steps']) assert.ok(catalog.includes(contract), `${contract} installation contract is present`);
for (const section of ['Como esta operação funciona','Templates','CRM & Pipeline','Dashboards','Documentação','Academy','Checklist pós-instalação','Por que recomendamos esta estratégia?']) assert.ok(details.includes(section), `${section} is rendered`);
assert.match(details, /onInstall\(card\.id\)/, 'installation reuses the existing marketplace callback');
console.log('Business Intelligence Kit architecture contracts passed');
