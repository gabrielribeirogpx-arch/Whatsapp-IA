'use client';

import { useCallback } from 'react';

/**
 * Stub temporário: instalação PWA ainda não está implementada.
 * Mantém a interface consumida pelo MobileChatShell sem ouvir
 * beforeinstallprompt nem exibir prompt nativo.
 */
export function usePWAInstall() {
  const promptInstall = useCallback(async () => false, []);

  return {
    isInstallable: false,
    promptInstall,
  };
}
