'use client';

/**
 * PushPermissionSheet.tsx — Wazza API Mobile
 * Light Mode · Identidade Verde #59C414
 */

import { Bell, X } from 'lucide-react';

interface PushPermissionSheetProps {
  open: boolean;
  onAllow: () => void;
  onDismiss: () => void;
}

export default function PushPermissionSheet({ open, onAllow, onDismiss }: PushPermissionSheetProps) {
  if (!open) return null;

  return (
    <>
      <div onClick={onDismiss} style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)',
        zIndex: 150, animation: 'fadeIn 0.2s ease',
      }} />

      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: '#FFFFFF', borderRadius: '20px 20px 0 0',
        padding: '20px 20px calc(env(safe-area-inset-bottom, 0px) + 24px)',
        zIndex: 160, animation: 'slideUp 0.25s ease',
      }}>
        <style>{`
          @keyframes fadeIn { from { opacity:0 } to { opacity:1 } }
          @keyframes slideUp {
            from { transform: translateY(100%); }
            to   { transform: translateY(0); }
          }
        `}</style>

        {/* Handle */}
        <div style={{
          width: '36px', height: '4px', background: '#E5E7EB',
          borderRadius: '2px', margin: '0 auto 20px',
        }} />

        {/* Close */}
        <button onClick={onDismiss} style={{
          position: 'absolute', top: '16px', right: '16px',
          background: '#F9FAFB', border: '1px solid #E5E7EB',
          borderRadius: '50%', width: '28px', height: '28px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', color: '#6B7280',
          WebkitTapHighlightColor: 'transparent',
        }}>
          <X size={15} />
        </button>

        {/* Icon */}
        <div style={{
          width: '56px', height: '56px', borderRadius: '16px',
          background: 'rgba(89,196,20,0.10)',
          border: '1px solid rgba(89,196,20,0.25)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 0 16px', color: '#59C414',
        }}>
          <Bell size={26} />
        </div>

        <h2 style={{
          margin: '0 0 8px', fontSize: '18px', fontWeight: 600,
          color: '#111827', fontFamily: "'DM Sans', sans-serif",
        }}>
          Ativar notificações
        </h2>

        <p style={{
          margin: '0 0 24px', fontSize: '14px', color: '#6B7280', lineHeight: 1.5,
        }}>
          Receba avisos quando um cliente solicitar atendimento humano ou enviar uma mensagem nova.
        </p>

        <button onClick={onAllow} style={{
          width: '100%', padding: '14px',
          background: '#59C414', border: 'none', borderRadius: '12px',
          fontSize: '15px', fontWeight: 600, color: '#fff',
          cursor: 'pointer', marginBottom: '10px',
          WebkitTapHighlightColor: 'transparent',
        }}>
          Permitir notificações
        </button>

        <button onClick={onDismiss} style={{
          width: '100%', padding: '14px',
          background: 'transparent', border: '1px solid #E5E7EB',
          borderRadius: '12px', fontSize: '14px', color: '#6B7280',
          cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
        }}>
          Agora não
        </button>
      </div>
    </>
  );
}
