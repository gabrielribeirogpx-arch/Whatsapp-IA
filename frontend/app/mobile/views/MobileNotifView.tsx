'use client';

/**
 * /frontend/components/mobile/MobileNotifView.tsx
 * Histórico local de notificações recebidas.
 * Armazena em memória (sessão). Em produção, persistir em IndexedDB.
 */

import { Bell, Trash2, MessageSquare, UserCheck } from 'lucide-react';
import { useEffect, useState } from 'react';

interface LocalNotif {
  id: string;
  title: string;
  body: string;
  type: 'message' | 'handoff' | 'generic';
  receivedAt: string;
  conversationId?: string;
}

// Singleton simples para notificações da sessão
let _notifs: LocalNotif[] = [];
export function addLocalNotif(n: Omit<LocalNotif, 'id' | 'receivedAt'>) {
  _notifs = [
    { ...n, id: `notif-${Date.now()}`, receivedAt: new Date().toISOString() },
    ..._notifs.slice(0, 49),
  ];
}

function timeLabel(iso: string): string {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000)     return 'agora';
  if (diff < 3_600_000)  return `${Math.floor(diff / 60_000)}m atrás`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h atrás`;
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}

export default function MobileNotifView() {
  const [notifs, setNotifs] = useState<LocalNotif[]>(_notifs);

  useEffect(() => {
    // Atualiza quando componente monta (pode ter chegado notif fora da tela)
    setNotifs([..._notifs]);
  }, []);

  function clearAll() {
    _notifs = [];
    setNotifs([]);
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100dvh',
        background: '#0a0a0f',
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      {/* Header */}
      <div
        style={{
          paddingTop: 'env(safe-area-inset-top, 0px)',
          padding: 'calc(env(safe-area-inset-top,0px) + 14px) 16px 14px',
          background: '#0a0a0f',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#e8e8f0', letterSpacing: '-0.3px' }}>
          Alertas
        </h1>
        {notifs.length > 0 && (
          <button
            onClick={clearAll}
            style={{
              background: 'transparent',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px',
              padding: '5px 10px',
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              fontSize: '12px',
              color: 'rgba(255,255,255,0.4)',
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            <Trash2 size={13} />
            Limpar
          </button>
        )}
      </div>

      {/* List */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          paddingBottom: 'calc(env(safe-area-inset-bottom,0px) + 72px)',
        }}
      >
        {notifs.length === 0 && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              gap: '12px',
              color: 'rgba(255,255,255,0.2)',
              paddingBottom: '60px',
            }}
          >
            <Bell size={40} strokeWidth={1.2} />
            <p style={{ margin: 0, fontSize: '14px' }}>Nenhuma notificação recebida</p>
          </div>
        )}

        {notifs.map((n) => (
          <div
            key={n.id}
            style={{
              display: 'flex',
              gap: '12px',
              padding: '12px 16px',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}
          >
            <span
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                background: n.type === 'handoff'
                  ? 'rgba(239,159,39,0.12)'
                  : 'rgba(124,110,245,0.12)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                color: n.type === 'handoff' ? '#EF9F27' : '#7c6ef5',
              }}
            >
              {n.type === 'handoff' ? <UserCheck size={17} /> : <MessageSquare size={17} />}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '2px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: '#e8e8f0' }}>{n.title}</span>
                <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', marginLeft: '8px', flexShrink: 0 }}>
                  {timeLabel(n.receivedAt)}
                </span>
              </div>
              <p style={{ margin: 0, fontSize: '12px', color: 'rgba(255,255,255,0.4)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {n.body}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
