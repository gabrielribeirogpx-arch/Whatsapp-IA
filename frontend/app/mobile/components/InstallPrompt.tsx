'use client';

/**
 * InstallPrompt.tsx — Wazza Inbox Mobile
 * Light Mode · Identidade Verde #59C414
 */

import { Download, X } from 'lucide-react';
import { useState } from 'react';

interface InstallPromptProps {
  onInstall: () => Promise<boolean>;
}

export default function InstallPrompt({ onInstall }: InstallPromptProps) {
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(false);

  if (dismissed) return null;

  async function handleInstall() {
    setLoading(true);
    const accepted = await onInstall();
    if (!accepted) setLoading(false);
  }

  return (
    <div style={{
      position: 'fixed', bottom: '80px', left: '12px', right: '12px',
      background: '#FFFFFF',
      border: '1px solid rgba(89,196,20,0.3)',
      borderRadius: '14px', padding: '12px 14px',
      display: 'flex', gap: '10px', alignItems: 'center',
      zIndex: 90,
      boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
      animation: 'slideUp 0.3s ease',
    }}>
      <style>{`
        @keyframes slideUp {
          from { transform: translateY(20px); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }
      `}</style>

      <span style={{
        width: '36px', height: '36px', borderRadius: '10px',
        background: 'rgba(89,196,20,0.10)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, color: '#59C414',
      }}>
        <Download size={18} />
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: '13px', fontWeight: 600, color: '#111827' }}>
          Instalar Wazza Inbox
        </p>
        <p style={{ margin: '1px 0 0', fontSize: '11px', color: '#6B7280' }}>
          Adicionar à tela inicial
        </p>
      </div>

      <button
        onClick={handleInstall}
        disabled={loading}
        style={{
          background: '#59C414', border: 'none', borderRadius: '8px',
          padding: '6px 12px', fontSize: '12px', fontWeight: 600,
          color: '#fff', cursor: loading ? 'default' : 'pointer',
          opacity: loading ? 0.7 : 1, flexShrink: 0,
          WebkitTapHighlightColor: 'transparent',
        }}
      >
        {loading ? '…' : 'Instalar'}
      </button>

      <button
        onClick={() => setDismissed(true)}
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: '#9CA3AF', padding: '4px', flexShrink: 0,
          WebkitTapHighlightColor: 'transparent',
        }}
      >
        <X size={15} />
      </button>
    </div>
  );
}
