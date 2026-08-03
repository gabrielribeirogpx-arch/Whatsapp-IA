export type ChoiceRecord = Record<string, unknown>;

const LABEL_FIELDS = ['label', 'title', 'name', 'text'];
const VALUE_FIELDS = ['id', 'value', 'key', 'uuid'];

export function choiceRecords(value: unknown): ChoiceRecord[] {
  if (Array.isArray(value)) return value.filter((item): item is ChoiceRecord => Boolean(item) && typeof item === 'object' && !Array.isArray(item));
  if (!value || typeof value !== 'object') return [];
  const object = value as ChoiceRecord;
  for (const key of ['items', 'data', 'results', 'appointments', 'options']) {
    if (Array.isArray(object[key])) return choiceRecords(object[key]);
  }
  return [];
}

export function detectChoiceSchema(value: unknown) {
  const records = choiceRecords(value);
  const fields = Array.from(new Set(records.slice(0, 5).flatMap((item) => Object.keys(item))));
  const find = (candidates: string[], fallback = '') => candidates.find((field) => fields.includes(field)) || fallback;
  return { records, fields, labelField: find(LABEL_FIELDS, fields.find((field) => typeof records[0]?.[field] === 'string') || fields[0] || 'label'), valueField: find(VALUE_FIELDS, fields[0] || 'id'), descriptionField: find(['description', 'subtitle', 'details']), iconField: find(['icon', 'emoji', 'image']) };
}

export function dynamicChoiceVariables(resultVariable: string, fields: string[]) {
  const root = resultVariable.trim() || 'selected_slot';
  return [root, `${root}_title`, `${root}_index`, `${root}_object`, ...fields.map((field) => `${root}_object.${field}`)];
}
