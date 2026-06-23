import { FormEvent, KeyboardEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { MoreVertical, Paperclip, Mic, RotateCcw, SendHorizontal, Smile, X } from 'lucide-react';
import { ChatMessage, Contact, ConversationMode } from '../lib/types';
import { IconMenu } from './icons';
import Avatar from './Avatar';
import MessageBubble from './MessageBubble';
import ConversationModeSelector from './ConversationModeSelector';
import { getWhatsappWindowStatus } from '@/lib/contactStatus';

type ChatWindowProps = {
  contact?: Contact;
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (value: string) => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  onToggleSidebar: () => void;
  mode: ConversationMode;
  presenceStatus?: string;
  typingText?: string;
  modeUpdating?: boolean;
  modeNotice?: string;
  modeError?: string;
  emptyStateMessage?: string;
  onModeChange: (mode: ConversationMode) => void;
  onResetConversation?: () => Promise<void> | void;
  resetInProgress?: boolean;
};

type ComposerAttachment = { id: string; file: File; previewUrl?: string };

const quickEmojis = ['😀', '😂', '😍', '👍', '🙏', '🔥', '🎉', '✅', '❤️', '👏', '🤖', '📎'];

function formatDateDivider(dateIso?: string) {
  if (!dateIso) return '';
  const date = new Date(dateIso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(date, today)) return 'Hoje';
  if (same(date, yesterday)) return 'Ontem';
  return date.toLocaleDateString('pt-BR', { weekday: 'long' });
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function ChatWindow(props: ChatWindowProps) {
  const { contact, messages, inputValue, onInputChange, onSend, onToggleSidebar, mode, presenceStatus, typingText, modeUpdating = false, modeNotice, modeError, emptyStateMessage, onModeChange, onResetConversation, resetInProgress = false } = props;
  const messagesRef = useRef<HTMLElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const isNearBottomRef = useRef(true);
  const previousContactIdRef = useRef<string | null>(null);
  const pendingInitialScrollRef = useRef(false);
  const previousLastMessageIdRef = useRef<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerFormRef = useRef<HTMLFormElement | null>(null);
  const emojiRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [showEmoji, setShowEmoji] = useState(false);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
  const [showNewMessageIndicator, setShowNewMessageIndicator] = useState(false);

  const isNearBottom = useCallback(() => {
    const el = messagesRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= 120;
  }, []);

  const scrollToBottom = useCallback(({ behavior = 'smooth' }: { behavior?: ScrollBehavior } = {}) => {
    const scroll = () => {
      const el = messagesRef.current;
      if (!el) return;
      messagesEndRef.current?.scrollIntoView({ block: 'end', behavior });
      el.scrollTo({ top: el.scrollHeight, behavior });
      isNearBottomRef.current = true;
      setShowNewMessageIndicator(false);
    };

    requestAnimationFrame(() => {
      scroll();
      setTimeout(scroll, 80);
    });
  }, []);

  const handleMessagesScroll = useCallback(() => {
    const nearBottom = isNearBottom();
    isNearBottomRef.current = nearBottom;
    if (nearBottom) setShowNewMessageIndicator(false);
  }, [isNearBottom]);

  useLayoutEffect(() => {
    const contactId = contact?.id ?? null;
    if (previousContactIdRef.current === contactId) return;

    previousContactIdRef.current = contactId;
    previousLastMessageIdRef.current = null;
    pendingInitialScrollRef.current = Boolean(contactId);
    isNearBottomRef.current = true;
    setShowNewMessageIndicator(false);
    if (contactId && messages.length > 0) scrollToBottom({ behavior: 'auto' });
  }, [contact?.id, messages.length, scrollToBottom]);

  useEffect(() => {
    if (!contact) return;
    const lastMessage = messages[messages.length - 1];
    const lastMessageId = lastMessage?.id ?? null;
    if (!lastMessageId) return;

    const isNewMessage = previousLastMessageIdRef.current !== null && previousLastMessageIdRef.current !== lastMessageId;
    const shouldForceInitialScroll = pendingInitialScrollRef.current;
    previousLastMessageIdRef.current = lastMessageId;

    if (shouldForceInitialScroll) {
      pendingInitialScrollRef.current = false;
      scrollToBottom({ behavior: 'auto' });
      return;
    }

    if (lastMessage.fromMe || isNearBottomRef.current) {
      scrollToBottom({ behavior: isNewMessage ? 'smooth' : 'auto' });
    } else if (isNewMessage) {
      setShowNewMessageIndicator(true);
    }
  }, [contact, messages, scrollToBottom]);

  useEffect(() => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = '0px';
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
  }, [inputValue]);

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      if (!emojiRef.current) return;
      if (!emojiRef.current.contains(event.target as Node)) setShowEmoji(false);
    };
    document.addEventListener('mousedown', onDocumentClick);
    return () => document.removeEventListener('mousedown', onDocumentClick);
  }, []);

  useEffect(() => {
    if (!contact) {
      setActionsOpen(false);
      setConfirmResetOpen(false);
    }
  }, [contact]);

  useEffect(() => () => attachments.forEach((a) => a.previewUrl && URL.revokeObjectURL(a.previewUrl)), [attachments]);

  const grouped = useMemo(() => {
    const out: Array<{ divider?: string; message?: ChatMessage; key: string }> = [];
    let lastDivider = '';
    messages.forEach((message) => {
      const divider = formatDateDivider(message.createdAt);
      if (divider && divider !== lastDivider) {
        out.push({ divider, key: `d-${message.id}` });
        lastDivider = divider;
      }
      out.push({ message, key: message.id });
    });
    return out;
  }, [messages]);

  const statusText = presenceStatus || getWhatsappWindowStatus(contact?.lastMessageAt);
  const assignedUserName = contact?.assignedUserName?.trim() || 'Atendente';
  const handoffStatus = contact?.awaitingHumanAssignment
    ? { label: '🔴 Aguardando Atendente', className: 'handoff' }
    : contact?.inHumanCare
      ? { label: `🟢 Em atendimento por ${assignedUserName}`, className: 'assigned' }
      : null;

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList?.length) return;
    const newAttachments = Array.from(fileList).map((file) => ({
      id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
      file,
      previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    }));
    setAttachments((current) => [...current, ...newAttachments]);
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      composerFormRef.current?.requestSubmit();
    }
  };

  return (
    <section className="wa-chat-window">
      <header className="wa-chat-header">
        <button type="button" className="wa-mobile-menu" onClick={onToggleSidebar} aria-label="Abrir conversas">
          <IconMenu width={20} />
        </button>
        {contact ? (
          <>
            <div className="wa-chat-contact">
              <Avatar name={contact.name} avatarUrl={contact.avatarUrl} phone={contact.phone} />
              <div>
                <h1>{contact.name || contact.phone}</h1>
                <p className="wa-contact-status away">
                  <span className="wa-status-dot" aria-hidden="true" />
                  {typingText || statusText}
                </p>
                {handoffStatus ? (
                  <div className={`wa-chat-handoff-badge ${handoffStatus.className}`}>{handoffStatus.label}</div>
                ) : null}
              </div>
            </div>
            <div className="wa-chat-actions">
              <div className="wa-chat-actions-row">
                <ConversationModeSelector mode={mode} loading={modeUpdating} disabled={!contact} onChange={onModeChange} />
                <div className="wa-conversation-menu-wrap">
                  <button
                    type="button"
                    className="wa-conversation-menu-trigger"
                    onClick={() => setActionsOpen((current) => !current)}
                    aria-label="Abrir menu da conversa"
                    aria-expanded={actionsOpen}
                  >
                    <MoreVertical size={18} />
                  </button>
                  {actionsOpen ? (
                    <div className="wa-conversation-menu" role="menu">
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setActionsOpen(false);
                          setConfirmResetOpen(true);
                        }}
                      >
                        <RotateCcw size={14} />
                        🔄 Resetar Conversa
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>
              {modeUpdating ? <p className="wa-mode-feedback">Atualizando modo...</p> : null}
              {!modeUpdating && modeNotice ? <p className="wa-mode-feedback success">{modeNotice}</p> : null}
              {!modeUpdating && modeError ? <p className="wa-mode-feedback error">{modeError}</p> : null}
            </div>
          </>
        ) : (
          <div>
            <h1>Selecione um contato</h1>
            <p>{emptyStateMessage || 'Escolha uma conversa para começar.'}</p>
          </div>
        )}
      </header>

      {confirmResetOpen ? (
        <div className="wa-reset-modal-backdrop" role="presentation">
          <div className="wa-reset-modal" role="dialog" aria-modal="true" aria-labelledby="wa-reset-title">
            <h2 id="wa-reset-title">Resetar conversa de teste</h2>
            <p>Esta ação apagará mensagens, sessões de fluxo e estado da conversa deste contato.</p>
            <p>Deseja continuar?</p>
            <div className="wa-reset-modal-actions">
              <button type="button" className="wa-reset-cancel" onClick={() => setConfirmResetOpen(false)} disabled={resetInProgress}>
                Cancelar
              </button>
              <button
                type="button"
                className="wa-reset-confirm"
                disabled={resetInProgress}
                onClick={async () => {
                  await onResetConversation?.();
                  setConfirmResetOpen(false);
                }}
              >
                {resetInProgress ? 'Resetando...' : 'Resetar'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <main
        className="wa-messages-panel"
        ref={messagesRef}
        onScroll={handleMessagesScroll}
        onLoadCapture={(event) => {
          const target = event.target as HTMLElement;
          if ((target.tagName === 'IMG' || target.tagName === 'VIDEO') && isNearBottomRef.current) {
            scrollToBottom({ behavior: 'auto' });
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (contact) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          handleFiles(event.dataTransfer.files);
        }}
      >
        {contact ? (
          grouped.map((item) =>
            item.divider ? (
              <div key={item.key} className="wa-date-divider">
                <span>{item.divider}</span>
              </div>
            ) : (
              <MessageBubble key={item.key} message={item.message!} />
            )
          )
        ) : (
          <p className="empty-state">Nenhuma conversa selecionada.</p>
        )}
        <div ref={messagesEndRef} aria-hidden="true" />
        {dragActive ? (
          <div className="wa-drop-overlay">
            <p>Solte para enviar</p>
          </div>
        ) : null}
      </main>
      {showNewMessageIndicator ? (
        <button type="button" className="wa-new-message-indicator" onClick={() => scrollToBottom()}>
          Nova mensagem
        </button>
      ) : null}
      {typingText ? <div className="wa-typing-indicator" role="status">{typingText}</div> : null}
      <form ref={composerFormRef} className="wa-message-composer premium" onSubmit={onSend}>
        <div className="wa-composer-input-wrap">
          <div className="wa-composer-tools">
            <div className="wa-emoji-wrap" ref={emojiRef}>
              <button type="button" className="wa-composer-icon-btn" onClick={() => setShowEmoji((prev) => !prev)} aria-label="Abrir emojis">
                <Smile size={18} />
              </button>
              {showEmoji ? (
                <div className="wa-emoji-picker">
                  {quickEmojis.map((emoji) => (
                    <button
                      type="button"
                      key={emoji}
                      onClick={() => {
                        onInputChange(`${inputValue}${emoji}`);
                        textareaRef.current?.focus();
                      }}
                    >
                      {emoji}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <button type="button" className="wa-composer-icon-btn" onClick={() => fileInputRef.current?.click()} aria-label="Adicionar anexo">
              <Paperclip size={18} />
            </button>
            <input
              ref={fileInputRef}
              hidden
              type="file"
              multiple
              accept="image/*,application/pdf,audio/*,video/*,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv"
              onChange={(event) => handleFiles(event.target.files)}
            />
          </div>
          <textarea
            ref={textareaRef}
            value={inputValue}
            onKeyDown={onComposerKeyDown}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder="Digite uma mensagem…"
            disabled={!contact}
            rows={1}
          />
          <button type="button" className="wa-composer-icon-btn" aria-label="Gravar áudio" disabled={!contact}>
            <Mic size={18} />
          </button>
          <button type="submit" className="wa-send-btn-modern" disabled={!contact || !inputValue.trim()} aria-label="Enviar">
            <SendHorizontal size={18} />
          </button>
        </div>
        {attachments.length ? (
          <div className="wa-attachment-preview">
            {attachments.map((attachment) => (
              <article key={attachment.id} className="wa-attachment-card">
                {attachment.previewUrl ? <img src={attachment.previewUrl} alt={attachment.file.name} /> : <div className="wa-attachment-generic">📄</div>}
                <div>
                  <p>{attachment.file.name}</p>
                  <small>{formatSize(attachment.file.size)}</small>
                </div>
                <button type="button" aria-label={`Remover ${attachment.file.name}`} onClick={() => setAttachments((current) => current.filter((file) => file.id !== attachment.id))}>
                  <X size={14} />
                </button>
              </article>
            ))}
          </div>
        ) : null}
      </form>
    </section>
  );
}
