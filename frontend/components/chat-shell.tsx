'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import ChatWindow from './ChatWindow';
import Sidebar from './Sidebar';
import CRMContactSidebar from './inbox/CRMContactSidebar';
import { getConversations, getMessagesByConversation, resetConversation, sendMessage, updateConversationMode } from '../lib/api';
import { ChatMessage, Contact, Conversation, ConversationMode, Message } from '../lib/types';
import { useRealtime } from '../hooks/useRealtime';

type ConversationAssignmentSnapshot = {
  mode: string;
  assignedUserId: string | null;
};

function getAssignedUserName(conversation: Conversation) {
  return conversation.assigned_user_name?.trim() || 'Atendente';
}

function toChatMessage(message: Message): ChatMessage {
  const parsedDate = new Date(message.created_at);
  const time = Number.isNaN(parsedDate.getTime())
    ? '--:--'
    : parsedDate.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

  return {
    id: String(message.id),
    text: message.content,
    fromMe: message.role === 'assistant',
    time,
    createdAt: message.created_at,
    status: message.role === 'assistant' ? 'read' : 'delivered',
    isNew: Date.now() - parsedDate.getTime() < 8000
  };
}

export default function ChatShell() {
  console.log("[COMPONENT RENDER] ChatShell");
  const router = useRouter();
  const searchParams = useSearchParams();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedContactId, setSelectedContactId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mode, setMode] = useState<ConversationMode>('human');
  const [modeUpdating, setModeUpdating] = useState(false);
  const [modeNotice, setModeNotice] = useState('');
  const [modeError, setModeError] = useState('');
  const [querySelectionMissing, setQuerySelectionMissing] = useState(false);
  const [crmOpen, setCrmOpen] = useState(false);
  const [handoffToast, setHandoffToast] = useState('');
  const [resetToast, setResetToast] = useState('');
  const [resetError, setResetError] = useState('');
  const [resettingConversation, setResettingConversation] = useState(false);
  const previousAssignmentRef = useRef<Map<string, ConversationAssignmentSnapshot>>(new Map());
  const hasLoadedConversationsRef = useRef(false);


  const playHumanHandoffSound = useCallback(() => {
    // TODO: Reativar notificação sonora quando houver um asset de áudio existente/aprovado no projeto.
  }, []);

  const applyConversations = useCallback(
    (items: Conversation[], options: { notifyHandoff?: boolean } = {}) => {
      const notifyHandoff = options.notifyHandoff ?? true;
      const previousAssignments = previousAssignmentRef.current;

      if (notifyHandoff && hasLoadedConversationsRef.current) {
        const assignedConversation = items.find((conversation) => {
          const previous = previousAssignments.get(String(conversation.id));
          const currentMode = String(conversation.mode || '').toLowerCase();
          const currentAssignedUserId = conversation.assigned_user_id ? String(conversation.assigned_user_id) : null;

          return Boolean(
            previous &&
              previous.mode === 'human' &&
              !previous.assignedUserId &&
              currentMode === 'human' &&
              currentAssignedUserId
          );
        });

        if (assignedConversation) {
          setHandoffToast(`${getAssignedUserName(assignedConversation)} assumiu o atendimento`);
        } else {
          const handoffConversation = items.find((conversation) => {
            const previous = previousAssignments.get(String(conversation.id));
            const currentMode = String(conversation.mode || '').toLowerCase();

            return Boolean(previous && previous.mode !== 'human' && currentMode === 'human');
          });

          if (handoffConversation) {
            const displayName = handoffConversation.name || handoffConversation.phone || 'Conversa';
            setHandoffToast(`Cliente solicitou atendimento humano: ${displayName}`);
            playHumanHandoffSound();
          }
        }
      }

      previousAssignmentRef.current = new Map(
        items.map((conversation) => [
          String(conversation.id),
          {
            mode: String(conversation.mode || '').toLowerCase(),
            assignedUserId: conversation.assigned_user_id ? String(conversation.assigned_user_id) : null
          }
        ])
      );
      hasLoadedConversationsRef.current = true;
      setConversations(items);
    },
    [playHumanHandoffSound]
  );


  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      router.replace('/login');
    }
  }, [router]);


  const fetchMessages = useCallback(
    async (conversationId: string) => {
      const conversation = conversations.find((item) => String(item.contact_id ?? item.id) === conversationId);

      if (!conversation) {
        setMessages([]);
        return;
      }

      const realMessages: Message[] = await getMessagesByConversation(String(conversation.id));
      setMessages(realMessages.map(toChatMessage));
    },
    [conversations]
  );


  const contacts = useMemo<Contact[]>(
    () =>
      conversations.map((conversation) => {
        return {
          id: String(conversation.contact_id ?? conversation.id),
          name: conversation.name,
          phone: conversation.phone,
          avatarUrl: conversation.avatar_url,
          stage: conversation.stage,
          score: conversation.score,
          lastMessage: conversation.last_message,
          lastMessageAt: conversation.updated_at,
          status: conversation.mode,
          assignedUserId: conversation.assigned_user_id ?? null,
          assignedUserName: conversation.assigned_user_name ?? null,
          awaitingHumanAssignment: String(conversation.mode || '').toLowerCase() === 'human' && !conversation.assigned_user_id,
          inHumanCare: String(conversation.mode || '').toLowerCase() === 'human' && Boolean(conversation.assigned_user_id)
        };
      }),
    [conversations]
  );

  const orderedContacts = useMemo(() => {
    const getPriority = (status?: string) => {
      const normalizedStatus = status?.toLowerCase();

      if (normalizedStatus === 'human') return 2;
      if (normalizedStatus === 'bot' || normalizedStatus === 'ai') return 1;
      return 0;
    };

    return [...contacts].sort((a, b) => {
      const priorityDiff = getPriority(a.status) - getPriority(b.status);
      if (priorityDiff !== 0) return priorityDiff;

      const dateA = a.lastMessageAt ? new Date(a.lastMessageAt).getTime() : 0;
      const dateB = b.lastMessageAt ? new Date(b.lastMessageAt).getTime() : 0;
      return dateB - dateA;
    });
  }, [contacts]);

  const unansweredCount = useMemo(
    () =>
      orderedContacts.filter((contact) => {
        const normalizedStatus = contact.status?.toLowerCase();
        return normalizedStatus !== 'human' && normalizedStatus !== 'bot' && normalizedStatus !== 'ai';
      }).length,
    [orderedContacts]
  );

  const humanRequestsCount = useMemo(
    () =>
      conversations.filter(
        (conversation) => String(conversation.mode || '').toLowerCase() === 'human' && !conversation.assigned_user_id
      ).length,
    [conversations]
  );

  const selectedContact = useMemo(
    () => contacts.find((contact) => contact.id === selectedContactId),
    [contacts, selectedContactId]
  );
  const selectedConversation = useMemo(
    () => conversations.find((item) => String(item.contact_id ?? item.id) === selectedContactId),
    [conversations, selectedContactId]
  );

  useEffect(() => {
    if (!selectedConversation) {
      return;
    }

    const currentMode = selectedConversation.mode?.toLowerCase();
    if (currentMode === 'bot' || currentMode === 'ai' || currentMode === 'human') {
      setMode(currentMode);
      return;
    }
  }, [selectedConversation]);



  useEffect(() => {
    if (!modeNotice && !modeError) return;

    const timeoutId = window.setTimeout(() => {
      setModeNotice('');
      setModeError('');
    }, 2200);

    return () => window.clearTimeout(timeoutId);
  }, [modeNotice, modeError]);

  useEffect(() => {
    if (!handoffToast) return;

    const timeoutId = window.setTimeout(() => setHandoffToast(''), 5000);

    return () => window.clearTimeout(timeoutId);
  }, [handoffToast]);

  useEffect(() => {
    if (!resetToast && !resetError) return;

    const timeoutId = window.setTimeout(() => {
      setResetToast('');
      setResetError('');
    }, 4000);

    return () => window.clearTimeout(timeoutId);
  }, [resetToast, resetError]);


  // A lógica de tempo real está centralizada nos hooks useRealtime abaixo

  useEffect(() => {
    console.log("[FRONTEND SELECTED CONVERSATION]", selectedConversation?.id);
  }, [selectedConversation]);

  useRealtime({
    wsUrl: `${process.env.NEXT_PUBLIC_API_URL?.replace('http', 'ws')}/api/dashboard/ws`,
    sseUrl: `${process.env.NEXT_PUBLIC_API_URL}/api/dashboard/stream`,
    tenantId: typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || '' : '',
    onMessage: (payload: { refresh?: string[] }) => {
      console.log("[WS MESSAGE]", payload);
      if (!payload?.refresh?.includes('conversations')) return;
      getConversations()
        .then((items) => applyConversations(items))
        .catch(() => undefined);
    }
  });

  const messageWsUrl = selectedConversation ? `${process.env.NEXT_PUBLIC_API_URL?.replace('http', 'ws')}/api/ws/messages/${selectedConversation.id}` : '';
  const messageSseUrl = selectedConversation ? `${process.env.NEXT_PUBLIC_API_URL}/api/sse/messages/${selectedConversation.id}` : '';
  
  console.log("[BEFORE MESSAGE HOOK]", selectedConversation?.id);
  console.log("[MESSAGE WS URL]", messageWsUrl);

  useRealtime({
    wsUrl: messageWsUrl,
    sseUrl: messageSseUrl,
    tenantId: typeof window !== 'undefined' ? localStorage.getItem('tenant_id') || '' : '',
    onMessage: (payload: { message?: { conversation_id: string } }) => {
      console.log("[WS MESSAGE RECEIVED CONVERSATION]", payload?.message?.conversation_id);
      if (!selectedContactId) return;
      fetchMessages(selectedContactId).catch(() => undefined);
      getConversations().then((items) => applyConversations(items)).catch(() => undefined);
    }
  });



  useEffect(() => {
    getConversations()
      .then((items) => {
        const targetContactId = searchParams.get('contact_id');
        const targetPhone = searchParams.get('phone');
        const normalizedTargetPhone = targetPhone ? targetPhone.replace(/\D/g, '') : '';

        applyConversations(items, { notifyHandoff: false });

        const matchedConversation = items.find((conversation) => {
          const byContactId = targetContactId
            ? String(conversation.contact_id ?? conversation.id) === targetContactId
            : false;

          const byPhone = normalizedTargetPhone
            ? conversation.phone.replace(/\D/g, '') === normalizedTargetPhone
            : false;

          return byContactId || byPhone;
        });

        if (matchedConversation) {
          setQuerySelectionMissing(false);
          setSelectedContactId(String(matchedConversation.contact_id ?? matchedConversation.id));
          return;
        }

        if (targetContactId || targetPhone) {
          setQuerySelectionMissing(true);
        }

        setSelectedContactId((current) => current || (items[0] ? String(items[0].contact_id ?? items[0].id) : ''));
      })
      .catch(() => setConversations([]));
  }, [searchParams, applyConversations]);


  function onSelectContact(contactId: string) {
    setSelectedContactId(contactId);
    setCrmOpen(true);
  }

  async function onSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedContact || !inputValue.trim()) return;

    const text = inputValue.trim();
    const now = new Date();
    const newMessage: ChatMessage = {
      id: `${now.getTime()}`,
      text,
      fromMe: true,
      time: now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((current) => [...current, newMessage]);
    setInputValue('');

    try {
      await sendMessage(selectedContact.phone, text, selectedContact.id);
    } catch (error) {
      console.error('Falha ao enviar para backend:', error);
    }
  }


  async function handleResetConversation() {
    if (!selectedConversation || resettingConversation) return;

    setResetToast('');
    setResetError('');
    setResettingConversation(true);

    try {
      await resetConversation(String(selectedConversation.id));
      const refreshedConversations = await getConversations();
      applyConversations(refreshedConversations, { notifyHandoff: false });
      setMessages([]);
      setSelectedContactId(refreshedConversations[0] ? String(refreshedConversations[0].contact_id ?? refreshedConversations[0].id) : '');
      setResetToast('Conversa resetada com sucesso.');
    } catch (err) {
      console.error('Erro ao resetar conversa:', err);
      setResetError('Não foi possível resetar a conversa.');
    } finally {
      setResettingConversation(false);
    }
  }

  async function handleChangeMode(newMode: ConversationMode) {
    if (!selectedConversation || modeUpdating || newMode === mode) return;

    const conversationId = String(selectedConversation.id);
    const previousMode = mode;

    setModeError('');
    setModeNotice('');
    setModeUpdating(true);

    try {
      await updateConversationMode(conversationId, newMode);

      setMode(newMode);
      const updatedConversations = conversations.map((conversation) =>
        conversation.id === selectedConversation.id ? { ...conversation, mode: newMode } : conversation
      );
      applyConversations(updatedConversations, { notifyHandoff: false });
      setModeNotice('Modo atualizado.');
    } catch (err) {
      console.error('Erro ao atualizar modo:', err);
      setMode(previousMode);
      setModeError('Não foi possível atualizar o modo.');
    } finally {
      setModeUpdating(false);
    }
  }

  return (
    <div className="wa-layout">
      <Sidebar
        contacts={orderedContacts}
        selectedContactId={selectedContactId}
        onSelectContact={onSelectContact}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
        unansweredCount={unansweredCount}
        humanRequestsCount={humanRequestsCount}
      />
      <ChatWindow
        contact={selectedContact}
        messages={messages}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSend={onSend}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
        mode={mode}
        modeUpdating={modeUpdating}
        modeNotice={modeNotice}
        modeError={modeError}
        emptyStateMessage={querySelectionMissing ? 'Conversa ainda não encontrada para este contato.' : undefined}
        resetInProgress={resettingConversation}
        onResetConversation={selectedConversation ? handleResetConversation : undefined}
        onModeChange={handleChangeMode}
      />
      {handoffToast ? <div className="wa-handoff-toast" role="status">{handoffToast}</div> : null}
      {resetToast ? <div className="wa-reset-toast success" role="status">{resetToast}</div> : null}
      {resetError ? <div className="wa-reset-toast error" role="alert">{resetError}</div> : null}
      <CRMContactSidebar contact={selectedContact} open={crmOpen} onClose={() => setCrmOpen(false)} />
    </div>
  );
}
