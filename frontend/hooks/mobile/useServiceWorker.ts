'use client';

import { useEffect, useState } from 'react';

interface ServiceWorkerState {
  registered: boolean;
  registration: ServiceWorkerRegistration | null;
  error: Error | null;
}

export function useServiceWorker(scriptUrl = '/sw.js') {
  const [state, setState] = useState<ServiceWorkerState>({
    registered: false,
    registration: null,
    error: null,
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return;

    let mounted = true;

    navigator.serviceWorker
      .register(scriptUrl, { scope: '/' })
      .then((registration) => {
        if (!mounted) return;
        setState({ registered: true, registration, error: null });
      })
      .catch((error: Error) => {
        if (!mounted) return;
        console.error('[PWA] Falha ao registrar service worker:', error);
        setState({ registered: false, registration: null, error });
      });

    return () => {
      mounted = false;
    };
  }, [scriptUrl]);

  return state;
}
