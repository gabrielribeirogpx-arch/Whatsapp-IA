'use client';

/**
 * /frontend/components/mobile/MobileChatShell.tsx  — v2
 *
 * Shell principal do Inbox Mobile. Mudanças vs v1:
 * - ❌ Polling 15s removido
 * - ✅ SSE via useSSE hook (mesmo endpoint do desktop)
 * - ✅ Handoff: aguardando / em atendimento por {nome}
 * - ✅ Assumir atendimento (PATCH /api/conversations/:id/assign)
 * - ✅ Resetar conversa (admin) POST /api/admin/reset-conversation/:id
 */

import {
  FormEvent, useCallback, useEffect, useMemo, useRef, useState,
} from 'react';

import {
  getConversations,
  getMessagesByConversation,
  sendMessage,
  updateConversationMode,
} from '@/lib/api';
import { ChatMessage, Contact, Conversation, ConversationMode, Message } from '@/lib/types';
import { usePushNotifications } from '@/hooks/mobile/usePushNotifications';
import { useServiceWorker } from '@/hooks/mobile/useServiceWorker';
import { usePWAInstall }     from '@/hooks/mobile/usePWAInstall';

import MobileConvoList      from './MobileConvoList';
import MobileChatView       from './MobileChatView';
import MobileNotifView      from './MobileNotifView';
import MobileProfileView    from './MobileProfileView';
import BottomNav            from './BottomNav';
import PushBanner           from './PushBanner';
import PushPermissionSheet  from './PushPermissionSheet';
import InstallPrompt        from './InstallPrompt';

export type MobileView = 'inbox' | 'chat' | 'notifs' | 'profile';

// ─── Helpers ──────────────────────────────────────────────────

function toChatMessage(msg: Message): ChatMessage {
  const d = new Date(msg.created_at);
  return {
    id: String(msg.id),
    text: msg.content,
    fromMe: msg.role === 'assistant',
    time: isNaN(d.getTime())
      ? '--:--'
      : d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
    createdAt: msg.created_at,
    status: msg.role === 'assistant' ? 'read' : 'delivered',
    isNew: Date.now() - d.getTime() < 5000,
  };
}

// ─── SSE Hook (inline, sem dependência extra) ─────────────────

/**
 * Conecta ao endpoint SSE existente e dispara callbacks quando
 * chegar evento relevante. Não toca em nada do Runtime V2.
 */
function useSSE(onEvent: (type: string, data: unknown) => void) {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const SSE_URL = process.env.NEXT_PUBLIC_SSE_URL || '/api/sse';
    let es: EventSource;
    let retryTimer: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource(SSE_URL, { withCredentials: true });

      es.addEventListener('conversation_updated', (e) => {
        try { cbRef.current('conversation_updated', JSON.parse(e.data)); } catch { /* noop */ }
      });

      es.addEventListener('new_message', (e) => {
        try { cbRef.current('new_message', JSON.parse(e.data)); } catch { /* noop */ }
      });

      es.addEventListener('handoff_requested', (e) => {
        try { cbRef.current('handoff_requested', JSON.parse(e.data)); } catch { /* noop */ }
      });

      es.addEventListener('message_assigned', (e) => {
        try { cbRef.current('message_assigned', JSON.parse(e.data)); } catch { /* noop */ }
      });

      es.onerror = () => {
        es.close();
        // Reconecta em 5s com backoff simples
        retryTimer = setTimeout(connect, 5000);
      };
    }

    connect();

    return () => {
      clearTimeout(retryTimer);
      es?.close();
    };
  }, []);
}

// ─── Main Component ───────────────────────────────────────────

export default function MobileChatShell() {
  // ── State ────────────────────────────────────────────────────
  const [view, setView]                     = useState<MobileView>('inbox');
  const [conversations, setConversations]   = useState<Conversation[]>([]);
  const [messages, setMessages]             = useState<ChatMessage[]>([]);
  const [selectedConvoId, setSelectedConvoId] = useState<string | null>(null);
  const [inputValue, setInputValue]         = useState('');
  const [filter, setFilter]                 = useState<'all'|'human'|'bot'|'pending'>('all');
  const [search, setSearch]                 = useState('');
  const [mode, setMode]                     = useState<ConversationMode>('human');
  const [modeUpdating, setModeUpdating]     = useState(false);
  const [loading, setLoading]               = useState(true);
  const [pushBanner, setPushBanner]         = useState<{ title: string; text: string } | null>(null);
  const [showPermSheet, setShowPermSheet]   = useState(false);

  // ── Hooks ────────────────────────────────────────────────────
  const { granted: pushGranted, requestPermission, subscribe } = usePushNotifications();
  const { isInstallable, promptInstall }                       = usePWAInstall();
  useServiceWorker('/sw.js');

  // ── Derived ─────────────────────────────────────────────────
  const contacts = useMemo<Contact[]>(() =>
    conversations.map(c => ({
      id:            String(c.contact_id ?? c.id),
      name:          c.name,
      phone:         c.phone,
      avatarUrl:     c.avatar_url,
      stage:         c.stage,
      score:         c.score,
      lastMessage:   c.last_message,
      lastMessageAt: c.updated_at,
      status:        c.mode,
    })),
    [conversations]
  );

  const selectedConvo = useMemo(
    () => conversations.find(c => c.id === selectedConvoId),
    [conversations, selectedConvoId]
  );

  const selectedContact = useMemo(
    () => contacts.find(c => c.id === String(selectedConvo?.contact_id ?? selectedConvo?.id)),
    [contacts, selectedConvo]
  );

  const pendingCount = useMemo(
    () => contacts.filter(c => !['human','bot','ai'].includes((c.status||'').toLowerCase())).length,
    [contacts]
  );

  // Handoff: nome do atendente atual
  const assignedUserName = useMemo(
    () => (selectedConvo as any)?.assigned_user_name || null,
    [selectedConvo]
  );

  // Admin: lê de cookie/contexto de auth. Aqui assume-se que existe
  // window.__WAZZA_USER__ ou similar. Ajuste conforme seu auth.
  const isAdmin = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return (window as any).__WAZZA_USER__?.role === 'admin';
  }, []);

  // ── Initial fetch ────────────────────────────────────────────
  const fetchConversations = useCallback(async () => {
    try {
      const data = await getConversations();
      setConversations(data);
    } catch (e) {
      console.error('[MobileChatShell] fetchConversations:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
    // SEM setInterval — SSE cuidará das atualizações
  }, [fetchConversations]);

  const fetchMessages = useCallback(async (convo: Conversation) => {
    try {
      const data = await getMessagesByConversation(String(convo.id));
      setMessages(data.map(toChatMessage));
    } catch (e) {
      console.error('[MobileChatShell] fetchMessages:', e);
    }
  }, []);

  // ── SSE handler ──────────────────────────────────────────────
  useSSE(useCallback((type: string, data: unknown) => {
    const d = data as Record<string, unknown>;

    if (type === 'conversation_updated') {
      const updated = d as Partial<Conversation> & { id: unknown };
      setConversations(prev =>
        prev.map(c => String(c.id) === String(updated.id) ? { ...c, ...updated } : c)
      );
      // Atualiza modo se é a conversa aberta
      if (selectedConvoId && String(updated.id) === selectedConvoId && updated.mode) {
        setMode((updated.mode as string).toLowerCase() as ConversationMode);
      }
    }

    if (type === 'new_message') {
      const msg = d as { conversation_id: unknown; message: Message };
      // Atualiza last_message na lista
      setConversations(prev =>
        prev.map(c =>
          String(c.id) === String(msg.conversation_id)
            ? { ...c, last_message: msg.message?.content, updated_at: msg.message?.created_at }
            : c
        )
      );
      // Appenda na thread aberta
      if (selectedConvoId && String(msg.conversation_id) === selectedConvoId) {
        setMessages(prev => [...prev, toChatMessage(msg.message)]);
      }
    }

    if (type === 'handoff_requested') {
      const h = d as { conversation_id: unknown; contact_name?: string };
      showBanner(
        'Solicitação de atendimento',
        `${h.contact_name || 'Cliente'} quer falar com um humano`
      );
      setConversations(prev =>
        prev.map(c =>
          String(c.id) === String(h.conversation_id) ? { ...c, mode: 'human' } : c
        )
      );
    }

    if (type === 'message_assigned') {
      const a = d as { conversation_id: unknown; user_name: string; user_id: string };
      setConversations(prev =>
        prev.map(c =>
          String(c.id) === String(a.conversation_id)
            ? { ...c, assigned_user_id: a.user_id, assigned_user_name: a.user_name } as any
            : c
        )
      );
    }
  }, [selectedConvoId]));

  // ── Handlers ─────────────────────────────────────────────────
  const showBanner = useCallback((title: string, text: string) => {
    setPushBanner({ title, text });
    setTimeout(() => setPushBanner(null), 4000);
  }, []);

  const openChat = useCallback((convoId: string) => {
    const convo = conversations.find(c => c.id === convoId);
    if (!convo) return;
    setSelectedConvoId(convoId);
    setMode((convo.mode?.toLowerCase() as ConversationMode) || 'human');
    setMessages([]);
    fetchMessages(convo);
    setView('chat');
  }, [conversations, fetchMessages]);

  const handleSend = useCallback(async (e?: FormEvent) => {
    e?.preventDefault();
    const text = inputValue.trim();
    if (!text || !selectedConvo || !selectedContact) return;

    const optimistic: ChatMessage = {
      id: `opt-${Date.now()}`,
      text,
      fromMe: true,
      time: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
      createdAt: new Date().toISOString(),
      status: 'sent',
      isNew: true,
    };
    setMessages(prev => [...prev, optimistic]);
    setInputValue('');

    try {
      await sendMessage(selectedContact.phone, text, selectedContact.id);
      setMessages(prev =>
        prev.map(m => m.id === optimistic.id ? { ...m, status: 'delivered' } : m)
      );
      setConversations(prev =>
        prev.map(c => c.id === selectedConvo.id
          ? { ...c, last_message: text, updated_at: new Date().toISOString() }
          : c
        )
      );
    } catch {
      setMessages(prev =>
        prev.map(m => m.id === optimistic.id ? { ...m, status: 'sent' } : m)
      );
    }
  }, [inputValue, selectedConvo, selectedContact]);

  const handleModeChange = useCallback(async (newMode: ConversationMode) => {
    if (!selectedConvo) return;
    setModeUpdating(true);
    try {
      await updateConversationMode(String(selectedConvo.id), newMode);
      setMode(newMode);
      setConversations(prev =>
        prev.map(c => c.id === selectedConvo.id ? { ...c, mode: newMode } : c)
      );
    } finally {
      setModeUpdating(false);
    }
  }, [selectedConvo]);

  // Assumir atendimento
  const handleAssume = useCallback(async () => {
    if (!selectedConvo) return;
    try {
      await fetch(`/api/conversations/${selectedConvo.id}/assign`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ self: true }),
        credentials: 'include',
      });
      // SSE vai atualizar; otimisticamente mostra "Você"
      setConversations(prev =>
        prev.map(c =>
          c.id === selectedConvo.id
            ? { ...c, assigned_user_name: 'Você' } as any
            : c
        )
      );
    } catch (e) {
      console.error('[MobileChatShell] handleAssume:', e);
    }
  }, [selectedConvo]);

  // Resetar conversa (admin)
  const handleReset = useCallback(async () => {
    if (!selectedConvo) return;
    try {
      await fetch(`/api/admin/reset-conversation/${selectedConvo.id}`, {
        method: 'POST',
        credentials: 'include',
      });
      // Volta para o inbox e recarrega
      setView('inbox');
      fetchConversations();
    } catch (e) {
      console.error('[MobileChatShell] handleReset:', e);
    }
  }, [selectedConvo, fetchConversations]);

  const handlePushAllow = useCallback(async () => {
    setShowPermSheet(false);
    await requestPermission();
    await subscribe();
  }, [requestPermission, subscribe]);

  // ── SW messages (notification tap) ──────────────────────────
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'NOTIFICATION_CLICK' && e.data.conversation_id) {
        openChat(String(e.data.conversation_id));
      }
    };
    navigator.serviceWorker?.addEventListener('message', handler);
    return () => navigator.serviceWorker?.removeEventListener('message', handler);
  }, [openChat]);

  // ─── Render ──────────────────────────────────────────────────
  return (
    <div
      style={{
        fontFamily: "'DM Sans', sans-serif",
        WebkitFontSmoothing: 'antialiased',
      }}
    >
      {/* ── Inbox list ── */}
      {view === 'inbox' && (
        <MobileConvoList
          conversations={conversations}
          loading={loading}
          filter={filter}
          search={search}
          onFilterChange={setFilter}
          onSearchChange={setSearch}
          onSelectConvo={openChat}
          onPushRequest={() => setShowPermSheet(true)}
          pushGranted={pushGranted}
          pendingCount={pendingCount}
        />
      )}

      {/* ── Chat thread ── */}
      {view === 'chat' && selectedContact && (
        <MobileChatView
          contact={selectedContact}
          messages={messages}
          inputValue={inputValue}
          onInputChange={setInputValue}
          onSend={handleSend}
          onBack={() => setView('inbox')}
          mode={mode}
          modeUpdating={modeUpdating}
          onModeChange={handleModeChange}
          assignedUserName={assignedUserName}
          isAdmin={isAdmin}
          onAssume={handleAssume}
          onReset={handleReset}
        />
      )}

      {/* ── Notifications ── */}
      {view === 'notifs' && <MobileNotifView />}

      {/* ── Profile ── */}
      {view === 'profile' && (
        <MobileProfileView
          isInstallable={isInstallable}
          onInstall={promptInstall}
          pushGranted={pushGranted}
          onPushRequest={() => setShowPermSheet(true)}
        />
      )}

      {/* ── Bottom nav (hidden in chat) ── */}
      {view !== 'chat' && (
        <BottomNav
          current={view}
          onChange={setView}
          pendingCount={pendingCount}
        />
      )}

      {/* ── Push banner ── */}
      {pushBanner && (
        <PushBanner
          title={pushBanner.title}
          text={pushBanner.text}
          onDismiss={() => setPushBanner(null)}
        />
      )}

      {/* ── Permission sheet ── */}
      <PushPermissionSheet
        open={showPermSheet}
        onAllow={handlePushAllow}
        onDismiss={() => setShowPermSheet(false)}
      />

      {/* ── Install prompt ── */}
      {isInstallable && <InstallPrompt onInstall={promptInstall} />}
    </div>
  );
}
