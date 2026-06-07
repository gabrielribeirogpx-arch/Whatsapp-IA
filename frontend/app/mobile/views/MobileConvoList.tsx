'use client';

/**
 * /frontend/components/mobile/MobileConvoList.tsx
 *
 * Lista de conversas do inbox mobile.
 * Filtros: all | human | bot | pending
 * Busca por nome/telefone.
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
  { id: 'all',     label: 'Todos'     },
  { id: 'human',   label: 'Humano'    },
  { id: 'bot',     label: 'Bot'       },
  { id: 'pending', label: 'Pendente'  },
];

function modeIcon(mode?: string) {
  const m = (mode || '').toLowerCase();
  if (m === 'human')            return <User size={12} />;
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
  return name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();
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
  // Filter + search
  const filtered = conversations.filter((c) => {
    const m = (c.mode || '').toLowerCase();

    if (filter === 'human'   && m !== 'human')             return false;
    if (filter === 'bot'     && m !== 'bot' && m !== 'ai') return false;
    if (filter === 'pending' && ['human', 'bot', 'ai'].includes(m)) return false;

    if (search) {
      const q = search.toLowerCase();
      return (
        (c.name   || '').toLowerCase().includes(q) ||
        (c.phone  || '').toLowerCase().includes(q)
      );
    }
    return true;
  });

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
      {/* ── Header ── */}
      <div
        style={{
          paddingTop: 'calc(env(safe-area-inset-top, 0px) + 12px)',
          padding: 'calc(env(safe-area-inset-top,0px) + 12px) 16px 0',
          background: '#0a0a0f',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: '#e8e8f0', letterSpacing: '-0.3px' }}>
              Inbox
            </h1>
            {pendingCount > 0 && (
              <p style={{ margin: 0, fontSize: '12px', color: '#EF9F27' }}>
                {pendingCount} aguardando atendimento
              </p>
            )}
          </div>

          <button
            onClick={onPushRequest}
            style={{
              background: pushGranted ? 'rgba(29,158,117,0.12)' : 'rgba(255,255,255,0.06)',
              border: `1px solid ${pushGranted ? 'rgba(29,158,117,0.3)' : 'rgba(255,255,255,0.1)'}`,
              borderRadius: '10px',
              width: '36px',
              height: '36px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: pushGranted ? '#1D9E75' : 'rgba(255,255,255,0.4)',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            {pushGranted ? <Bell size={17} /> : <BellOff size={17} />}
          </button>
        </div>

        {/* Search */}
        <div
          style={{
            position: 'relative',
            marginBottom: '10px',
          }}
        >
          <Search
            size={15}
            style={{
              position: 'absolute',
              left: '10px',
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'rgba(255,255,255,0.3)',
              pointerEvents: 'none',
            }}
          />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Buscar conversa…"
            style={{
              width: '100%',
              height: '38px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '10px',
              paddingLeft: '32px',
              paddingRight: search ? '32px' : '12px',
              fontSize: '14px',
              color: '#e8e8f0',
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
          {search && (
            <button
              onClick={() => onSearchChange('')}
              style={{
                position: 'absolute',
                right: '8px',
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                color: 'rgba(255,255,255,0.3)',
                padding: '2px',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Filters */}
        <div
          style={{
            display: 'flex',
            gap: '6px',
            overflowX: 'auto',
            paddingBottom: '10px',
            scrollbarWidth: 'none',
          }}
        >
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => onFilterChange(f.id)}
              style={{
                flexShrink: 0,
                padding: '5px 12px',
                borderRadius: '20px',
                fontSize: '12px',
                fontWeight: filter === f.id ? 600 : 400,
                background: filter === f.id ? '#7c6ef5' : 'rgba(255,255,255,0.06)',
                border: filter === f.id ? 'none' : '1px solid rgba(255,255,255,0.08)',
                color: filter === f.id ? '#fff' : 'rgba(255,255,255,0.45)',
                cursor: 'pointer',
                WebkitTapHighlightColor: 'transparent',
                transition: 'all 0.15s',
              }}
            >
              {f.label}
              {f.id === 'pending' && pendingCount > 0 && (
                <span
                  style={{
                    marginLeft: '5px',
                    background: 'rgba(239,159,39,0.3)',
                    color: '#EF9F27',
                    borderRadius: '10px',
                    padding: '0 5px',
                    fontSize: '10px',
                    fontWeight: 700,
                  }}
                >
                  {pendingCount}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── List ── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          paddingBottom: 'calc(env(safe-area-inset-bottom,0px) + 72px)',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {loading && (
          <div style={{ padding: '40px 0', textAlign: 'center', color: 'rgba(255,255,255,0.2)', fontSize: '13px' }}>
            Carregando conversas…
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div style={{ padding: '48px 20px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: '15px', color: 'rgba(255,255,255,0.25)' }}>
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
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '12px 16px',
        background: 'transparent',
        border: 'none',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        cursor: 'pointer',
        textAlign: 'left',
        WebkitTapHighlightColor: 'rgba(124,110,245,0.08)',
        transition: 'background 0.1s',
      }}
    >
      {/* Avatar */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        {convo.avatar_url ? (
          <img
            src={convo.avatar_url}
            alt=""
            style={{ width: '44px', height: '44px', borderRadius: '50%', objectFit: 'cover' }}
          />
        ) : (
          <div
            style={{
              width: '44px',
              height: '44px',
              borderRadius: '50%',
              background: 'rgba(124,110,245,0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
              fontWeight: 600,
              color: '#7c6ef5',
              border: isPending ? '2px solid #EF9F27' : 'none',
            }}
          >
            {initials(convo.name)}
          </div>
        )}
        {/* Mode dot */}
        <span
          style={{
            position: 'absolute',
            bottom: '1px',
            right: '1px',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            background: color,
            border: '2px solid #0a0a0f',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
          }}
        >
          {modeIcon(convo.mode)}
        </span>
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '2px' }}>
          <span
            style={{
              fontSize: '14px',
              fontWeight: 600,
              color: '#e8e8f0',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: '180px',
            }}
          >
            {convo.name || convo.phone || '—'}
          </span>
          <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', flexShrink: 0, marginLeft: '8px' }}>
            {timeLabel(convo.updated_at)}
          </span>
        </div>

        <p
          style={{
            margin: 0,
            fontSize: '12px',
            color: isPending ? '#EF9F27' : 'rgba(255,255,255,0.4)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            fontWeight: isPending ? 500 : 400,
          }}
        >
          {isPending ? '⚡ Aguardando atendente' : (convo.last_message || 'Sem mensagens')}
        </p>
      </div>
    </button>
  );
}
