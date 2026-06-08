'use client';

/**
 * MobileNotifView.tsx — Wazza Inbox Mobile
 * Light Mode · Identidade Verde #59C414
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
    setNotifs([..._notifs]);
  }, []);

  function clearAll() {
    _notifs = [];
    setNotifs([]);
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100dvh',
      background: '#FFFFFF', fontFamily: "'DM Sans', sans-serif",
    }}>
      {/* Header */}
      <div style={{
        padding: 'calc(env(safe-area-inset-top,0px) + 14px) 16px 14px',
        background: '#FFFFFF', borderBottom: '1px solid #E5E7EB',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#111827', letterSpacing: '-0.3px' }}>
          Alertas
        </h1>
        {notifs.length > 0 && (
          <button onClick={clearAll} style={{
            background: 'transparent', border: '1px solid #E5E7EB',
            borderRadius: '8px', padding: '5px 10px',
            display: 'flex', alignItems: 'center', gap: '5px',
            fontSize: '12px', color: '#6B7280',
            cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
          }}>
            <Trash2 size={13} />
            Limpar
          </button>
        )}
      </div>

      {/* List */}
      <div style={{
        flex: 1, overflowY: 'auto',
        paddingBottom: 'calc(env(safe-area-inset-bottom,0px) + 72px)',
        background: '#F9FAFB',
      }}>
        {notifs.length === 0 && (
          <div style={{
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            height: '100%', gap: '12px', color: '#D1D5DB', paddingBottom: '60px',
          }}>
            <Bell size={40} strokeWidth={1.2} />
            <p style={{ margin: 0, fontSize: '14px', color: '#9CA3AF' }}>
              Nenhuma notificação recebida
            </p>
          </div>
        )}

        {notifs.map((n) => (
          <div key={n.id} style={{
            display: 'flex', gap: '12px', padding: '12px 16px',
            background: '#FFFFFF', borderBottom: '1px solid #F3F4F6',
          }}>
            <span style={{
              width: '36px', height: '36px', borderRadius: '10px',
              background: n.type === 'handoff'
                ? 'rgba(239,159,39,0.10)'
                : 'rgba(89,196,20,0.10)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
              color: n.type === 'handoff' ? '#EF9F27' : '#59C414',
            }}>
              {n.type === 'handoff' ? <UserCheck size={17} /> : <MessageSquare size={17} />}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '2px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>{n.title}</span>
                <span style={{ fontSize: '11px', color: '#9CA3AF', marginLeft: '8px', flexShrink: 0 }}>
                  {timeLabel(n.receivedAt)}
                </span>
              </div>
              <p style={{
                margin: 0, fontSize: '12px', color: '#6B7280',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {n.body}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
