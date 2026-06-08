'use client';

/**
 * MobileConvoList.tsx — Wazza Inbox Mobile
 * Light Mode · Identidade Verde #59C414
 */

import { Search, Bell, BellOff, Bot, User, Clock, X } from 'lucide-react';
import type { Conversation } from '@/lib/types';

interface MobileConvoListProps {
  conversations: Conversation[];
  loading: boolean;
  filter: 'all' | 'human' | 'bot' | 'pending';
  search: string;
  onFilterChange: (f: 'all' | 'human' | 'bot' | 'pending') => void;
  onSearchChange: (s: string) => void;
  onSelectConvo: (id: string) => void;
  onPushRequest: () => void;
  pushGranted: boolean;
  pendingCount: number;
}

const FILTERS: { id: 'all' | 'human' | 'bot' | 'pending'; label: string }[] = [
  { id: 'all',     label: 'Todos'    },
  { id: 'human',   label: 'Humano'   },
  { id: 'bot',     label: 'Bot'      },
  { id: 'pending', label: 'Pendente' },
];

function modeIcon(mode?: string) {
  const m = (mode || '').toLowerCase();
  if (m === 'human')             return <User size={12} />;
  if (m === 'bot' || m === 'ai') return <Bot size={12} />;
  return <Clock size={12} />;
}

function modeColor(mode?: string): string {
  const m = (mode || '').toLowerCase();
  if (m === 'human')             return '#1D9E75';
  if (m === 'bot' || m === 'ai') return '#378ADD';
  return '#EF9F27';
}

function initials(name?: string): string {
  if (!name) return '?';
  return name.split(' ').slice(0, 2).map((w) => w[0]).join('').toUpperCase();
}

function timeLabel(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  if (diffMs < 60_000)     return 'agora';
  if (diffMs < 3_600_000)  return `${Math.floor(diffMs / 60_000)}m`;
  if (diffMs < 86_400_000) return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}

export default function MobileConvoList({
  conversations,
  loading,
  filter,
  search,
  onFilterChange,
  onSearchChange,
  onSelectConvo,
  onPushRequest,
  pushGranted,
  pendingCount,
}: MobileConvoListProps) {
  const filtered = conversations.filter((c) => {
    const m = (c.mode || '').toLowerCase();
    if (filter === 'human'   && m !== 'human')              return false;
    if (filter === 'bot'     && m !== 'bot' && m !== 'ai')  return false;
    if (filter === 'pending' && ['human', 'bot', 'ai'].includes(m)) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        (c.name  || '').toLowerCase().includes(q) ||
        (c.phone || '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100dvh',
      background: '#FFFFFF',
      fontFamily: "'DM Sans', sans-serif",
    }}>
      {/* ── Header ── */}
      <div style={{
        padding: 'calc(env(safe-area-inset-top,0px) + 12px) 16px 0',
        background: '#FFFFFF',
        borderBottom: '1px solid #E5E7EB',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <div>
            {/* Logo Wazza */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
              <img
                src="/Logo.svg"
                alt="Wazza"
                style={{
                  height: '24px',
                  width: 'auto',
                  objectFit: 'contain',
                }}
              />
              <h1
                style={{
                  margin: 0,
                  fontSize: '20px',
                  fontWeight: 700,
                  color: '#111827',
                  letterSpacing: '-0.3px'
                 }}
              >
                Wazza Inbox
              </h1>
            </div>
            {pendingCount > 0 && (
              <p style={{ margin: 0, fontSize: '12px', color: '#EF9F27', fontWeight: 500 }}>
                {pendingCount} aguardando atendimento
              </p>
            )}
          </div>

          <button
            onClick={onPushRequest}
            style={{
              background: pushGranted ? 'rgba(89,196,20,0.10)' : '#F9FAFB',
              border: `1px solid ${pushGranted ? 'rgba(89,196,20,0.4)' : '#E5E7EB'}`,
              borderRadius: '10px',
              width: '36px', height: '36px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
              color: pushGranted ? '#59C414' : '#9CA3AF',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            {pushGranted ? <Bell size={17} /> : <BellOff size={17} />}
          </button>
        </div>

        {/* Search */}
        <div style={{ position: 'relative', marginBottom: '10px' }}>
          <Search size={15} style={{
            position: 'absolute', left: '10px', top: '50%',
            transform: 'translateY(-50%)', color: '#9CA3AF', pointerEvents: 'none',
          }} />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Buscar conversa…"
            style={{
              width: '100%', height: '38px',
              background: '#F9FAFB',
              border: '1px solid #E5E7EB',
              borderRadius: '10px',
              paddingLeft: '32px',
              paddingRight: search ? '32px' : '12px',
              fontSize: '14px', color: '#111827',
              outline: 'none', boxSizing: 'border-box',
            }}
          />
          {search && (
            <button onClick={() => onSearchChange('')} style={{
              position: 'absolute', right: '8px', top: '50%',
              transform: 'translateY(-50%)',
              background: 'transparent', border: 'none',
              cursor: 'pointer', color: '#9CA3AF',
              padding: '2px', WebkitTapHighlightColor: 'transparent',
            }}>
              <X size={14} />
            </button>
          )}
        </div>

        {/* Filters */}
        <div style={{
          display: 'flex', gap: '6px', overflowX: 'auto',
          paddingBottom: '10px', scrollbarWidth: 'none',
        }}>
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => onFilterChange(f.id)}
              style={{
                flexShrink: 0, padding: '5px 12px', borderRadius: '20px',
                fontSize: '12px', fontWeight: filter === f.id ? 600 : 400,
                background: filter === f.id ? '#59C414' : '#F9FAFB',
                border: filter === f.id ? 'none' : '1px solid #E5E7EB',
                color: filter === f.id ? '#fff' : '#6B7280',
                cursor: 'pointer', WebkitTapHighlightColor: 'transparent',
                transition: 'all 0.15s',
              }}
            >
              {f.label}
              {f.id === 'pending' && pendingCount > 0 && (
                <span style={{
                  marginLeft: '5px',
                  background: 'rgba(239,159,39,0.15)',
                  color: '#EF9F27',
                  borderRadius: '10px', padding: '0 5px',
                  fontSize: '10px', fontWeight: 700,
                }}>
                  {pendingCount}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── List ── */}
      <div style={{
        flex: 1, overflowY: 'auto',
        paddingBottom: 'calc(env(safe-area-inset-bottom,0px) + 72px)',
        WebkitOverflowScrolling: 'touch',
        background: '#FFFFFF',
      }}>
        {loading && (
          <div style={{ padding: '40px 0', textAlign: 'center', color: '#9CA3AF', fontSize: '13px' }}>
            Carregando conversas…
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div style={{ padding: '48px 20px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: '15px', color: '#9CA3AF' }}>
              {search ? 'Nenhuma conversa encontrada.' : 'Nenhuma conversa nesta categoria.'}
            </p>
          </div>
        )}

        {filtered.map((convo) => (
          <ConvoRow key={convo.id} convo={convo} onClick={() => onSelectConvo(String(convo.id))} />
        ))}
      </div>
    </div>
  );
}

// ── Row individual ──────────────────────────────────────────────

interface ConvoRowProps {
  convo: Conversation;
  onClick: () => void;
}

function ConvoRow({ convo, onClick }: ConvoRowProps) {
  const isPending = !['human', 'bot', 'ai'].includes((convo.mode || '').toLowerCase());
  const color = modeColor(convo.mode);

  return (
    <button
      onClick={onClick}
      style={{
        width: '100%',
        display: 'flex', alignItems: 'center', gap: '12px',
        padding: '12px 16px',
        background: 'transparent', border: 'none',
        borderBottom: '1px solid #F3F4F6',
        cursor: 'pointer', textAlign: 'left',
        WebkitTapHighlightColor: 'rgba(89,196,20,0.06)',
        transition: 'background 0.1s',
      }}
    >
      {/* Avatar */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        {convo.avatar_url ? (
          <img src={convo.avatar_url} alt="" style={{
            width: '46px', height: '46px', borderRadius: '50%', objectFit: 'cover',
          }} />
        ) : (
          <div style={{
            width: '46px', height: '46px', borderRadius: '50%',
            background: 'rgba(89,196,20,0.10)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '15px', fontWeight: 600, color: '#59C414',
            border: isPending ? '2px solid #EF9F27' : '2px solid transparent',
          }}>
            {initials(convo.name)}
          </div>
        )}
        {/* Mode dot */}
        <span style={{
          position: 'absolute', bottom: '1px', right: '1px',
          width: '16px', height: '16px', borderRadius: '50%',
          background: color, border: '2px solid #FFFFFF',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff',
        }}>
          {modeIcon(convo.mode)}
        </span>
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '2px' }}>
          <span style={{
            fontSize: '14px', fontWeight: 600, color: '#111827',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px',
          }}>
            {convo.name || convo.phone || '—'}
          </span>
          <span style={{ fontSize: '11px', color: '#9CA3AF', flexShrink: 0, marginLeft: '8px' }}>
            {timeLabel(convo.updated_at)}
          </span>
        </div>
        <p style={{
          margin: 0, fontSize: '12px',
          color: isPending ? '#EF9F27' : '#6B7280',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: isPending ? 500 : 400,
        }}>
          {isPending ? '⚡ Aguardando atendente' : (convo.last_message || 'Sem mensagens')}
        </p>
      </div>
    </button>
  );
}
