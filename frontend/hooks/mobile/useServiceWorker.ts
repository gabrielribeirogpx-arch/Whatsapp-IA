'use client';

/**
 * Stub temporário: service worker ainda não está implementado.
 * Aceita a mesma assinatura do hook real para preservar chamadas existentes,
 * mas não registra nenhum worker.
 */
export function useServiceWorker(_scriptUrl?: string) {
  return {
    registered: false,
    registration: null,
  };
}
