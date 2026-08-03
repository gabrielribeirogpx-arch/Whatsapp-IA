export type HandleDirection = 'source' | 'target';

export type ContractNode = {
  type?: string | null;
  data?: Record<string, unknown> | null;
};

export const LEGACY_HANDLE_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  sucesso: 'success',
  erro: 'error',
  tempo_esgotado: 'timeout',
});

const normalize = (value: unknown) => String(value ?? '').trim().toLowerCase();
const handleId = (value: unknown, fallback: string) =>
  normalize(value).replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;

/** The single editor contract for handles rendered by each node kind. */
export function getCanonicalNodeHandles(node: ContractNode): { source: Set<string>; target: Set<string> } {
  const type = normalize(node.type || node.data?.type);
  const data = (node.data || {}) as Record<string, any>;
  const target = new Set(['default']);
  let source = new Set(['default']);

  if (type === 'mcp_tool') source = new Set(['success', 'error', 'timeout']);
  else if (type === 'condition') source = new Set(['true', 'false']);
  else if (type === 'choice_dynamic' || (type === 'choice' && normalize(data.options_mode || data.option_mode) === 'dynamic')) {
    source = new Set(['default']);
  } else if (type === 'choice') {
    const choices = Array.isArray(data.buttons) ? data.buttons : Array.isArray(data.options) ? data.options : [];
    source = new Set(choices.map((choice: Record<string, unknown>, index: number) =>
      handleId(choice.handleId || choice.handle_id || choice.value || choice.id || choice.label, `option_${index + 1}`)));
  } else if (type === 'data_collection') {
    source = new Set(['success', 'invalid', 'cancel', 'timeout']);
    if (data.auto_retry_invalid === true && data.attempts_exceeded_behavior === 'end') source.delete('invalid');
  }
  return { source, target };
}

export const normalizeLegacyHandle = (value: unknown) => {
  const normalized = normalize(value);
  return LEGACY_HANDLE_ALIASES[normalized] || normalized;
};

