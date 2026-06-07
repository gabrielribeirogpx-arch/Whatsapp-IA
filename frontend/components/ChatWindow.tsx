import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Paperclip, Mic, SendHorizontal, Smile, X } from 'lucide-react';
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
  modeUpdating?: boolean;
  modeNotice?: string;
  modeError?: string;
  emptyStateMessage?: string;
  onModeChange: (mode: ConversationMode) => void;
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
  const { contact, messages, inputValue, onInputChange, onSend, onToggleSidebar, mode, modeUpdating = false, modeNotice, modeError, emptyStateMessage, onModeChange } = props;
  const messagesRef = useRef<HTMLElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerFormRef = useRef<HTMLFormElement | null>(null);
  const emojiRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [showEmoji, setShowEmoji] = useState(false);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    if (!messagesRef.current) return;
    const el = messagesRef.current;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom < 120) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, [messages]);

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

  const statusText = getWhatsappWindowStatus(contact?.lastMessageAt);
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
                  {statusText}
                </p>
                {handoffStatus ? (
                  <div className={`wa-chat-handoff-badge ${handoffStatus.className}`}>{handoffStatus.label}</div>
                ) : null}
              </div>
            </div>
            <div className="wa-chat-actions">
              <ConversationModeSelector mode={mode} loading={modeUpdating} disabled={!contact} onChange={onModeChange} />
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
      <main
        className="wa-messages-panel"
        ref={messagesRef}
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
        {dragActive ? (
          <div className="wa-drop-overlay">
            <p>Solte para enviar</p>
          </div>
        ) : null}
      </main>
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
