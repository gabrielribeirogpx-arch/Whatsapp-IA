export type SimulatorIssue = {
  code: string;
  node_id?: string | null;
  message: string;
};

export type SimulatorError = {
  title: string;
  message?: string;
  errors: SimulatorIssue[];
  retryable: boolean;
};

const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' ? value as Record<string, unknown> : null;

/** Turns fetch/Axios/backend failures into safe, user-facing simulator copy. */
export function parseSimulatorError(error: unknown): SimulatorError {
  const root = record(error);
  const response = record(root?.response);
  const responseData = record(response?.data);
  const body = responseData || root;
  const detailValue = body?.detail;
  const detail = record(detailValue);
  const rawIssues = detail?.errors || body?.errors;
  const errors = Array.isArray(rawIssues)
    ? rawIssues.flatMap((item) => {
        const value = record(item);
        if (!value || typeof value.message !== 'string') return [];
        return [{
          code: typeof value.code === 'string' ? value.code : 'FLOW_VALIDATION_ERROR',
          node_id: typeof value.node_id === 'string' ? value.node_id : null,
          message: value.message,
        }];
      })
    : [];

  if (errors.length) {
    return { title: 'Não foi possível iniciar a simulação', errors, retryable: false };
  }

  const networkFailure = error instanceof TypeError
    || root?.name === 'AbortError'
    || root?.code === 'ECONNABORTED';
  if (networkFailure && !body?.detail && !body?.errors) {
    return {
      title: 'Não foi possível iniciar a simulação',
      message: 'Verifique sua conexão e tente novamente.',
      errors: [],
      retryable: true,
    };
  }

  const message = typeof detailValue === 'string'
    ? detailValue
    : typeof detail?.message === 'string'
      ? detail.message
      : typeof body?.message === 'string'
        ? body.message
        : undefined;
  if (message) return { title: 'Não foi possível iniciar a simulação', message, errors: [], retryable: false };

  return {
    title: 'Não foi possível iniciar a simulação',
    message: 'Recebemos uma resposta inesperada. Tente novamente.',
    errors: [],
    retryable: true,
  };
}
