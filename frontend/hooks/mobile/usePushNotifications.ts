'use client';

import { useCallback } from 'react';

/**
 * Stub temporário: push notifications ainda não estão implementadas.
 * Mantém a API esperada pelo MobileChatShell sem solicitar permissões,
 * registrar subscriptions ou acessar serviços externos.
 */
export function usePushNotifications() {
  const requestPermission = useCallback(async () => false, []);
  const subscribe = useCallback(async () => null, []);

  return {
    granted: false,
    requestPermission,
    subscribe,
  };
}
