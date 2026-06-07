'use client';

/**
 * /frontend/components/mobile/MobileChatView.tsx
 *
 * Thread de chat mobile com:
 * - Bolhas de mensagem
 * - Status de handoff humano (aguardando / em atendimento)
 * - Botão "Assumir atendimento"
 * - Troca de modo bot/humano
 * - Menu overflow com "Resetar conversa" (admin only)
 * - Input + enviar
 */

import {
  ArrowLeft, Bot, User, Clock, Send, Paperclip,
  MoreVertical, UserCheck, RefreshCw, CheckCheck, Check,
} from 'lucide-react';
import { useRef, useEffect, useState, FormEvent } from 'react';
import type { ChatMessage, Contact, ConversationMode } from '@/lib/types';

interface MobileChatViewProps {
  contact: Contact;
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (v: string) => void;
  onSend: (e?: FormEvent) => void;
  onBack: () => void;
  mode: ConversationMode;
  modeUpdating: boolean;
  onModeChange: (m: ConversationMode) => void;
  // Optional: handoff / admin features
  assignedUserName?: string | null;   // nome do atendente atual se mode=human
  currentUserId?: string;             // id do usuário logado
  isAdmin?: boolean;                  // para mostrar "Resetar"
  onAssume?: () => void;              // assume a conversa
  onReset?: () => void;               // admin reset
}

function statusIcon(status?: string) {
  if (status === 'read')      return <CheckCheck size={12} style={{ color: '#7c6ef5' }} />;
  if (status === 'delivered') return <CheckCheck size={12} style={{ color: 'rgba(255,255,255,0.4)' }} />;
  return <Check size={12} style={{ color: 'rgba(255,255,255,0.3)' }} />;
}

export default function MobileChatView({
  contact,
  messages,
  inputValue,
  onInputChange,
  onSend,
  onBack,
  mode,
  modeUpdating,
  onModeChange,
  assignedUserName,
  isAdmin = false,
  onAssume,
  onReset,
}: MobileChatViewProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  // Scroll to bottom on new messages
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  // Auto-resize textarea
  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    onInputChange(el.value);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  }

  // ── Handoff status bar ──────────────────────────────────────
  const isHuman = mode === 'human';
  const hasAssigned = !!assignedUserName;

  let handoffBg = '';
  let handoffText = '';
  if (isHuman && !hasAssigned) {
    handoffBg = 'rgba(239,159,39,0.1)';
    handoffText = '🔴 Aguardando atendente';
  } else if (isHuman && hasAssigned) {
    handoffBg = 'rgba(29,158,117,0.1)';
    handoffText = `🟢 Em atendimento por ${assignedUserName}`;
  }

  const initials = (contact.name || '?')
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();

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
          paddingTop: 'env(safe-area-inset-top, 0px)',
          background: '#0d0d14',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          {/* Back */}
          <button
            onClick={onBack}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#7c6ef5',
              cursor: 'pointer',
              padding: '6px',
              marginLeft: '-6px',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            <ArrowLeft size={22} />
          </button>

          {/* Avatar */}
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              background: 'rgba(124,110,245,0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '12px',
              fontWeight: 600,
              color: '#7c6ef5',
              flexShrink: 0,
            }}
          >
            {initials}
          </div>

          {/* Name + mode */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <p
              style={{
                margin: 0,
                fontSize: '15px',
                fontWeight: 600,
                color: '#e8e8f0',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {contact.name || contact.phone}
            </p>
            <p style={{ margin: 0, fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>
              {contact.phone}
            </p>
          </div>

          {/* Mode toggle */}
          <ModeChip mode={mode} updating={modeUpdating} onChange={onModeChange} />

          {/* Overflow menu */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'rgba(255,255,255,0.4)',
                cursor: 'pointer',
                padding: '6px',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              <MoreVertical size={18} />
            </button>

            {menuOpen && (
              <>
                <div
                  onClick={() => setMenuOpen(false)}
                  style={{ position: 'fixed', inset: 0, zIndex: 99 }}
                />
                <div
                  style={{
                    position: 'absolute',
                    top: '36px',
                    right: 0,
                    background: '#1a1a2e',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '12px',
                    overflow: 'hidden',
                    zIndex: 100,
                    minWidth: '170px',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  }}
                >
                  {onAssume && (
                    <MenuOption
                      icon={<UserCheck size={15} />}
                      label="Assumir atendimento"
                      onClick={() => { setMenuOpen(false); onAssume(); }}
                    />
                  )}
                  {isAdmin && onReset && (
                    <MenuOption
                      icon={<RefreshCw size={15} />}
                      label="Resetar conversa"
                      danger
                      onClick={() => { setMenuOpen(false); setConfirmReset(true); }}
                    />
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Handoff status bar */}
        {handoffText && (
          <div
            style={{
              background: handoffBg,
              padding: '6px 16px',
              fontSize: '12px',
              color: isHuman && !hasAssigned ? '#EF9F27' : '#1D9E75',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span>{handoffText}</span>
            {isHuman && !hasAssigned && onAssume && (
              <button
                onClick={onAssume}
                style={{
                  background: '#EF9F27',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '3px 10px',
                  fontSize: '11px',
                  fontWeight: 600,
                  color: '#0a0a0f',
                  cursor: 'pointer',
                  WebkitTapHighlightColor: 'transparent',
                }}
              >
                Assumir
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── Messages ── */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '12px 12px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'rgba(255,255,255,0.2)',
              fontSize: '13px',
            }}
          >
            Nenhuma mensagem ainda
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={msg.id} msg={msg} prevFromMe={i > 0 ? messages[i - 1].fromMe : undefined} />
        ))}
      </div>

      {/* ── Input ── */}
      <div
        style={{
          background: '#0d0d14',
          borderTop: '1px solid rgba(255,255,255,0.06)',
          padding: '8px 12px',
          paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 8px)',
          display: 'flex',
          alignItems: 'flex-end',
          gap: '8px',
          flexShrink: 0,
        }}
      >
        <button
          style={{
            background: 'transparent',
            border: 'none',
            color: 'rgba(255,255,255,0.3)',
            cursor: 'pointer',
            padding: '8px',
            flexShrink: 0,
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          <Paperclip size={19} />
        </button>

        <div
          style={{
            flex: 1,
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.09)',
            borderRadius: '20px',
            padding: '8px 14px',
            minHeight: '38px',
            display: 'flex',
            alignItems: 'flex-end',
          }}
        >
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="Escreva uma mensagem…"
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              fontSize: '14px',
              color: '#e8e8f0',
              resize: 'none',
              fontFamily: "'DM Sans', sans-serif",
              lineHeight: 1.5,
              maxHeight: '120px',
              overflowY: 'auto',
              padding: 0,
            }}
          />
        </div>

        <button
          onClick={() => onSend()}
          disabled={!inputValue.trim()}
          style={{
            width: '38px',
            height: '38px',
            borderRadius: '50%',
            background: inputValue.trim() ? '#7c6ef5' : 'rgba(255,255,255,0.07)',
            border: 'none',
            cursor: inputValue.trim() ? 'pointer' : 'default',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: inputValue.trim() ? '#fff' : 'rgba(255,255,255,0.2)',
            transition: 'background 0.15s, color 0.15s',
            flexShrink: 0,
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          <Send size={17} />
        </button>
      </div>

      {/* ── Confirm Reset Dialog ── */}
      {confirmReset && (
        <ConfirmSheet
          message="Resetar esta conversa? O bot voltará ao início do fluxo."
          confirmLabel="Resetar"
          onConfirm={() => { setConfirmReset(false); onReset?.(); }}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </div>
  );
}

// ── Message Bubble ──────────────────────────────────────────────

function MessageBubble({
  msg,
  prevFromMe,
}: {
  msg: ChatMessage;
  prevFromMe?: boolean;
}) {
  const isMine = msg.fromMe;
  const grouped = prevFromMe === isMine;

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isMine ? 'flex-end' : 'flex-start',
        marginTop: grouped ? '2px' : '8px',
      }}
    >
      <div
        style={{
          maxWidth: '78%',
          background: isMine ? '#7c6ef5' : 'rgba(255,255,255,0.08)',
          borderRadius: isMine
            ? '18px 18px 4px 18px'
            : '18px 18px 18px 4px',
          padding: '8px 12px',
          position: 'relative',
        }}
      >
        <p
          style={{
            margin: 0,
            fontSize: '14px',
            color: isMine ? '#fff' : '#e8e8f0',
            lineHeight: 1.45,
            wordBreak: 'break-word',
          }}
        >
          {msg.text}
        </p>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '3px',
            marginTop: '3px',
          }}
        >
          <span
            style={{
              fontSize: '10px',
              color: isMine ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.3)',
            }}
          >
            {msg.time}
          </span>
          {isMine && statusIcon(msg.status)}
        </div>
      </div>
    </div>
  );
}

// ── Mode Chip ───────────────────────────────────────────────────

const MODES: { id: ConversationMode; label: string; icon: React.ReactNode; color: string; bg: string }[] = [
  { id: 'human', label: 'Humano', icon: <User size={11} />, color: '#1D9E75', bg: 'rgba(29,158,117,0.15)' },
  { id: 'bot',   label: 'Bot',    icon: <Bot size={11} />,  color: '#378ADD', bg: 'rgba(55,138,221,0.15)' },
];

function ModeChip({
  mode,
  updating,
  onChange,
}: {
  mode: ConversationMode;
  updating: boolean;
  onChange: (m: ConversationMode) => void;
}) {
  const current = MODES.find((m) => m.id === mode) || MODES[0];
  const next = MODES.find((m) => m.id !== mode) || MODES[1];

  return (
    <button
      onClick={() => !updating && onChange(next.id)}
      disabled={updating}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        background: current.bg,
        border: `1px solid ${current.color}33`,
        borderRadius: '20px',
        padding: '4px 9px',
        fontSize: '11px',
        fontWeight: 600,
        color: current.color,
        cursor: updating ? 'default' : 'pointer',
        opacity: updating ? 0.6 : 1,
        WebkitTapHighlightColor: 'transparent',
        transition: 'all 0.15s',
      }}
    >
      {current.icon}
      {current.label}
    </button>
  );
}

// ── Menu Option ────────────────────────────────────────────────

function MenuOption({
  icon,
  label,
  onClick,
  danger = false,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '12px 14px',
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        fontSize: '13px',
        color: danger ? '#e24b4a' : '#e8e8f0',
        textAlign: 'left',
        WebkitTapHighlightColor: 'transparent',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      {icon}
      {label}
    </button>
  );
}

// ── Confirm Sheet ───────────────────────────────────────────────

function ConfirmSheet({
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <div
        onClick={onCancel}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 150 }}
      />
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          background: '#0d0d14',
          borderRadius: '20px 20px 0 0',
          padding: '20px 20px calc(env(safe-area-inset-bottom,0px) + 20px)',
          zIndex: 160,
        }}
      >
        <div
          style={{
            width: '36px',
            height: '4px',
            background: 'rgba(255,255,255,0.15)',
            borderRadius: '2px',
            margin: '0 auto 16px',
          }}
        />
        <p style={{ margin: '0 0 20px', fontSize: '14px', color: 'rgba(255,255,255,0.6)', textAlign: 'center' }}>
          {message}
        </p>
        <button
          onClick={onConfirm}
          style={{
            width: '100%',
            padding: '13px',
            background: '#e24b4a',
            border: 'none',
            borderRadius: '12px',
            fontSize: '15px',
            fontWeight: 600,
            color: '#fff',
            cursor: 'pointer',
            marginBottom: '8px',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          {confirmLabel}
        </button>
        <button
          onClick={onCancel}
          style={{
            width: '100%',
            padding: '13px',
            background: 'transparent',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '12px',
            fontSize: '14px',
            color: 'rgba(255,255,255,0.4)',
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          Cancelar
        </button>
      </div>
    </>
  );
}
