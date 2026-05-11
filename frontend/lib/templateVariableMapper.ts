import { TEMPLATE_VARIABLES, TEMPLATE_VARIABLES_BY_LABEL, TemplateVariableDefinition } from './templateVariables';

export type TemplateVariableMapItem = {
  position: number;
  key: string;
  label: string;
  example: string;
};

type MapperResult = {
  bodyText: string;
  variables: TemplateVariableMapItem[];
  errors: string[];
};

const friendlyVariableRegex = /\{([^{}]+)\}/g;

export function friendlyToMeta(body: string): MapperResult {
  const errors: string[] = [];
  const found = new Map<string, TemplateVariableMapItem>();
  let nextPosition = 1;

  const bodyText = body.replace(friendlyVariableRegex, (full, rawLabel) => {
    const label = String(rawLabel).trim();
    const variable = TEMPLATE_VARIABLES_BY_LABEL.get(label.toLowerCase());

    if (!variable) {
      errors.push(`Variável desconhecida: {${label}}`);
      return full;
    }

    const existing = found.get(variable.key);
    if (existing) return `{{${existing.position}}}`;

    const created: TemplateVariableMapItem = {
      position: nextPosition,
      key: variable.key,
      label: variable.label,
      example: variable.example
    };
    found.set(variable.key, created);
    nextPosition += 1;
    return `{{${created.position}}}`;
  });

  if ((body.match(/\{/g) || []).length !== (body.match(/\}/g) || []).length) {
    errors.push('Há uma variável incompleta no texto.');
  }

  return { bodyText, variables: Array.from(found.values()), errors };
}

export function metaToFriendly(bodyText: string, variablesJson?: TemplateVariableMapItem[] | null): string {
  const indexMap = new Map<number, TemplateVariableMapItem>();
  (variablesJson || []).forEach(item => indexMap.set(Number(item.position), item));

  return bodyText.replace(/\{\{(\d+)\}\}/g, (_m, raw) => {
    const position = Number(raw);
    const mapped = indexMap.get(position);
    if (mapped?.label) return `{${mapped.label}}`;
    return `{Variável ${position}}`;
  });
}

export function renderExample(bodyText: string, variablesJson?: TemplateVariableMapItem[] | null): string {
  const indexMap = new Map<number, TemplateVariableMapItem>();
  (variablesJson || []).forEach(item => indexMap.set(Number(item.position), item));

  return bodyText.replace(/\{\{(\d+)\}\}/g, (_m, raw) => indexMap.get(Number(raw))?.example || `Valor ${raw}`);
}

export function validateMetaVariables(bodyText: string): string {
  if (!bodyText?.trim()) return 'Template sem body não é permitido.';
  const regex = /\{\{(\d+)\}\}/g;
  const matches: number[] = [];
  let current: RegExpExecArray | null = null;
  while ((current = regex.exec(bodyText)) !== null) matches.push(Number(current[1]));
  if (matches.length === 0) return '';
  const unique = Array.from(new Set(matches)).sort((a, b) => a - b);
  for (let i = 1; i <= unique.length; i += 1) {
    if (unique[i - 1] !== i) return 'Variáveis com buracos são inválidas. Ex: {{1}} {{3}}';
  }
  return '';
}

export function getTemplateVariableByLabel(label: string): TemplateVariableDefinition | undefined {
  return TEMPLATE_VARIABLES_BY_LABEL.get(label.trim().toLowerCase());
}

export { TEMPLATE_VARIABLES };
