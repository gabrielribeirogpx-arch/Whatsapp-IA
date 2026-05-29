'use client';

import { useEffect, useId, useRef, useState } from 'react';

declare global {
  interface Window {
    turnstile?: {
      render: (container: string | HTMLElement, options: Record<string, unknown>) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId: string) => void;
    };
    __wazzaTurnstileLoaded?: boolean;
  }
}

type TurnstileWidgetProps = {
  action: 'login' | 'register' | 'forgot-password';
  token: string;
  onToken: (token: string) => void;
  onError?: (message: string) => void;
};

const SCRIPT_ID = 'cloudflare-turnstile-script';
const DEV_TOKEN = 'dev-turnstile-token';

function isDevelopmentFallback(siteKey: string | undefined) {
  return !siteKey && process.env.NODE_ENV !== 'production';
}

export default function TurnstileWidget({ action, token, onToken, onError }: TurnstileWidgetProps) {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  const rawId = useId().replace(/:/g, '');
  const containerId = `turnstile-${action}-${rawId}`;
  const widgetIdRef = useRef<string | null>(null);
  const [ready, setReady] = useState(() => (typeof window !== 'undefined' ? Boolean(window.__wazzaTurnstileLoaded) : false));
  const [fallbackDev, setFallbackDev] = useState(false);

  useEffect(() => {
    if (isDevelopmentFallback(siteKey)) {
      setFallbackDev(true);
      onToken(DEV_TOKEN);
      return;
    }

    if (!siteKey) {
      onToken('');
      onError?.('Proteção anti-bot indisponível. Configure a chave pública do Turnstile.');
      return;
    }

    if (window.__wazzaTurnstileLoaded && window.turnstile) {
      setReady(true);
      return;
    }

    const existingScript = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    const script = existingScript ?? document.createElement('script');
    script.id = SCRIPT_ID;
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    script.defer = true;
    script.onload = () => {
      window.__wazzaTurnstileLoaded = true;
      setReady(true);
    };
    script.onerror = () => onError?.('Não foi possível carregar a proteção anti-bot. Verifique sua conexão.');

    if (!existingScript) document.head.appendChild(script);
  }, [onError, onToken, siteKey]);

  useEffect(() => {
    if (!ready || !siteKey || !window.turnstile || widgetIdRef.current) return;

    widgetIdRef.current = window.turnstile.render(`#${containerId}`, {
      sitekey: siteKey,
      action,
      theme: 'light',
      size: 'flexible',
      retry: 'auto',
      'refresh-expired': 'auto',
      callback: (value: string) => onToken(value),
      'expired-callback': () => {
        onToken('');
        if (widgetIdRef.current) window.turnstile?.reset(widgetIdRef.current);
      },
      'error-callback': () => {
        onToken('');
        onError?.('Validação anti-bot falhou. Tente novamente.');
      }
    });

    return () => {
      if (widgetIdRef.current) {
        window.turnstile?.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [action, containerId, onError, onToken, ready, siteKey]);

  if (fallbackDev) {
    return (
      <div className="turnstile-shell turnstile-shell--dev" aria-live="polite">
        <span>Proteção anti-bot em modo desenvolvimento</span>
      </div>
    );
  }

  return (
    <div className="turnstile-wrapper" aria-live="polite">
      <div id={containerId} className="turnstile-shell" />
      {!token && <p className="turnstile-hint">Validação discreta de segurança obrigatória.</p>}
    </div>
  );
}
