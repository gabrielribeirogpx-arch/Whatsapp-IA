'use client';

/**
 * PushBanner.tsx — Wazza Inbox Mobile
 * Light Mode · Identidade Verde #59C414
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
    <div style={{
      position: 'fixed',
      top: 'calc(env(safe-area-inset-top, 0px) + 12px)',
      left: '12px', right: '12px',
      zIndex: 200,
      background: '#FFFFFF',
      border: '1px solid rgba(89,196,20,0.25)',
      borderRadius: '14px', padding: '12px 14px',
      display: 'flex', gap: '10px', alignItems: 'flex-start',
      boxShadow: '0 8px 24px rgba(0,0,0,0.10)',
      animation: 'slideDown 0.25s ease',
    }}>
      <style>{`
        @keyframes slideDown {
          from { transform: translateY(-20px); opacity: 0; }
          to   { transform: translateY(0);     opacity: 1; }
        }
      `}</style>

      <span style={{
        width: '32px', height: '32px', borderRadius: '8px',
        background: 'rgba(89,196,20,0.10)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, color: '#59C414',
      }}>
        <MessageSquare size={16} />
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          margin: 0, fontSize: '13px', fontWeight: 600, color: '#111827',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {title}
        </p>
        <p style={{
          margin: '2px 0 0', fontSize: '12px', color: '#6B7280',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {text}
        </p>
      </div>

      <button onClick={dismiss} style={{
        background: 'transparent', border: 'none',
        cursor: 'pointer', color: '#9CA3AF',
        padding: '2px', flexShrink: 0,
        WebkitTapHighlightColor: 'transparent',
      }}>
        <X size={16} />
      </button>
    </div>
  );
}
