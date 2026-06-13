'use client';

/**
 * PushBanner.tsx — Wazza Inbox Mobile
 * Light Mode · Identidade Verde #59C414
 */

import { Bell, ClipboardList, MessageSquare, X } from 'lucide-react';
import { useState } from 'react';

interface PushBannerProps {
  title: string;
  text: string;
  variant?: 'message' | 'team_notification' | 'task_created';
  onDismiss?: () => void;
}

const variantStyles = {
  message: {
    border: 'rgba(89,196,20,0.25)',
    bg: 'rgba(89,196,20,0.10)',
    color: '#59C414',
    shadow: 'rgba(0,0,0,0.10)',
    Icon: MessageSquare,
  },
  team_notification: {
    border: 'rgba(37,99,235,0.24)',
    bg: 'rgba(37,99,235,0.10)',
    color: '#2563EB',
    shadow: 'rgba(37,99,235,0.16)',
    Icon: Bell,
  },
  task_created: {
    border: 'rgba(5,150,105,0.24)',
    bg: 'rgba(16,185,129,0.12)',
    color: '#059669',
    shadow: 'rgba(5,150,105,0.18)',
    Icon: ClipboardList,
  },
};

export default function PushBanner({
  title,
  text,
  variant = 'message',
  onDismiss,
}: PushBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const style = variantStyles[variant];
  const Icon = style.Icon;
  const lines = text.split('\n').filter(Boolean);

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
      border: `1px solid ${style.border}`,
      borderRadius: '16px', padding: '12px 14px',
      display: 'flex', gap: '10px', alignItems: 'flex-start',
      boxShadow: `0 12px 30px ${style.shadow}`,
      animation: 'slideDown 0.25s ease',
    }}>
      <style>{`
        @keyframes slideDown {
          from { transform: translateY(-20px); opacity: 0; }
          to   { transform: translateY(0);     opacity: 1; }
        }
      `}</style>

      <span style={{
        width: '34px', height: '34px', borderRadius: '10px',
        background: style.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, color: style.color,
      }}>
        <Icon size={17} />
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          margin: 0, fontSize: '13px', fontWeight: 700, color: '#111827',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {title}
        </p>
        <div style={{ marginTop: '3px' }}>
          {lines.length > 0 ? lines.map((line, index) => (
            <p
              key={`${line}-${index}`}
              style={{
                margin: index === 0 ? 0 : '2px 0 0',
                fontSize: index === 0 ? '12px' : '11px',
                fontWeight: index === 0 && variant === 'task_created' ? 700 : 500,
                color: index === 0 ? '#374151' : '#6B7280',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {line}
            </p>
          )) : null}
        </div>
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
