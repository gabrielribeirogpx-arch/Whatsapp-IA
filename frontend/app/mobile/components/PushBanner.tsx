'use client';

/**
 * /frontend/components/mobile/PushBanner.tsx
 * Toast banner que aparece no topo quando chega push enquanto app está aberto.
 */

import { MessageSquare, X } from 'lucide-react';
import { useState } from 'react';

interface PushBannerProps {
  title: string;
  text: string;
  onDismiss?: () => void;
}

export default function PushBanner({ title, text, onDismiss }: PushBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  function dismiss() {
    setDismissed(true);
    onDismiss?.();
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 'calc(env(safe-area-inset-top, 0px) + 12px)',
        left: '12px',
        right: '12px',
        zIndex: 200,
        background: '#1a1a2e',
        border: '1px solid rgba(124,110,245,0.3)',
        borderRadius: '14px',
        padding: '12px 14px',
        display: 'flex',
        gap: '10px',
        alignItems: 'flex-start',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        animation: 'slideDown 0.25s ease',
      }}
    >
      <style>{`
        @keyframes slideDown {
          from { transform: translateY(-20px); opacity: 0; }
          to   { transform: translateY(0);     opacity: 1; }
        }
      `}</style>

      <span
        style={{
          width: '32px',
          height: '32px',
          borderRadius: '8px',
          background: 'rgba(124,110,245,0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          color: '#7c6ef5',
        }}
      >
        <MessageSquare size={16} />
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <p
          style={{
            margin: 0,
            fontSize: '13px',
            fontWeight: 600,
            color: '#e8e8f0',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </p>
        <p
          style={{
            margin: '2px 0 0',
            fontSize: '12px',
            color: 'rgba(255,255,255,0.5)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {text}
        </p>
      </div>

      <button
        onClick={dismiss}
        style={{
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: 'rgba(255,255,255,0.3)',
          padding: '2px',
          flexShrink: 0,
          WebkitTapHighlightColor: 'transparent',
        }}
      >
        <X size={16} />
      </button>
    </div>
  );
}
