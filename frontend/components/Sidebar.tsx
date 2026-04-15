import { useMemo, useState } from 'react';
import Avatar from './Avatar';
import { IconClose, IconMenu } from './icons';
import { Contact } from '../lib/types';

type SidebarProps = {
  contacts: Contact[];
  selectedContactId: string;
  onSelectContact: (contactId: string) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  unansweredCount: number;
};

export default function Sidebar({
  contacts,
  selectedContactId,
  onSelectContact,
  sidebarOpen,
  onToggleSidebar,
  unansweredCount: _unansweredCount
}: SidebarProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [activeFilter, setActiveFilter] = useState<'all' | 'pending' | 'human' | 'ai'>('all');

  const filterChips = [
    { id: 'all', label: 'Todas' },
    { id: 'pending', label: 'Não respondidas' },
    { id: 'human', label: 'Humanos' },
    { id: 'ai', label: 'IA' }
  ] as const;

  function formatPhone(phone: string) {
    const digits = phone.replace(/\D/g, '');

    if (digits.length === 13) {
      return `+${digits.slice(0, 2)} (${digits.slice(2, 4)}) ${digits.slice(4, 9)}-${digits.slice(9)}`;
    }

    if (digits.length === 12) {
      return `+${digits.slice(0, 2)} (${digits.slice(2, 4)}) ${digits.slice(4, 8)}-${digits.slice(8)}`;
    }

    if (digits.length === 11) {
      return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
    }

    if (digits.length === 10) {
      return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
    }

    return phone;
  }

  function formatRelativeTime(isoDate?: string | null) {
    if (!isoDate) return 'agora';

    const date = new Date(isoDate);
    if (Number.isNaN(date.getTime())) return 'agora';

    const diffInSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (diffInSeconds < 60) return 'agora';

    const diffInMinutes = Math.floor(diffInSeconds / 60);
    if (diffInMinutes < 60) return `há ${diffInMinutes} min`;

    const diffInHours = Math.floor(diffInMinutes / 60);
    if (diffInHours < 24) return diffInHours === 1 ? 'há 1 hora' : `há ${diffInHours} horas`;

    const diffInDays = Math.floor(diffInHours / 24);
    return diffInDays === 1 ? 'há 1 dia' : `há ${diffInDays} dias`;
  }

  function getBadge(status?: string) {
    const normalizedStatus = status?.toLowerCase();

    if (normalizedStatus === 'human') {
      return { label: '👤 Humano', className: 'human' };
    }

    if (normalizedStatus === 'bot' || normalizedStatus === 'ai') {
      return { label: '🤖 IA', className: 'ai' };
    }

    return { label: '⏳ Aguardando', className: 'pending' };
  }

  const filteredContacts = useMemo(() => {
    const normalizedSearchTerm = searchTerm.trim().toLowerCase();

    return contacts.filter((contact) => {
      const normalizedStatus = (contact.status || '').toLowerCase();
      const matchesFilter =
        activeFilter === 'all'
          ? true
          : activeFilter === 'pending'
            ? normalizedStatus === 'pending'
            : activeFilter === 'human'
              ? normalizedStatus === 'human'
              : normalizedStatus === 'ai' || normalizedStatus === 'bot';

      if (!matchesFilter) return false;

      if (!normalizedSearchTerm) return true;

      const searchFields = [contact.phone, contact.name || '', contact.lastMessage || '']
        .join(' ')
        .toLowerCase();

      return searchFields.includes(normalizedSearchTerm);
    });
  }, [contacts, activeFilter, searchTerm]);

  return (
    <aside className={`wa-sidebar ${sidebarOpen ? 'open' : ''}`}>
      <header className="wa-sidebar-header">
        <div>
          <h2>Inbox</h2>
          <p>Conversas em tempo real</p>
        </div>
        <button type="button" className="wa-sidebar-toggle" onClick={onToggleSidebar} aria-label="Alternar sidebar">
          {sidebarOpen ? <IconClose width={20} /> : <IconMenu width={20} />}
        </button>
      </header>

      <div className="wa-contact-list">
        <div className="wa-sidebar-search-wrapper">
          <span className="wa-sidebar-search-icon" aria-hidden="true">
            🔍
          </span>
          <input
            type="text"
            className="wa-sidebar-search-input"
            placeholder="Buscar ou iniciar conversa"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            aria-label="Buscar conversa"
          />
        </div>

        <div className="wa-filter-chips" role="tablist" aria-label="Filtros de conversa">
          {filterChips.map((chip) => {
            const isActive = activeFilter === chip.id;
            return (
              <button
                key={chip.id}
                type="button"
                className={`wa-filter-chip ${isActive ? 'active' : ''}`}
                onClick={() => setActiveFilter(chip.id)}
              >
                {chip.label}
              </button>
            );
          })}
        </div>

        {filteredContacts.length === 0 ? (
          <p className="wa-inbox-empty">Nenhuma conversa encontrada</p>
        ) : null}

        {filteredContacts.map((contact) => {
          const isActive = contact.id === selectedContactId;
          const displayName = contact.name || formatPhone(contact.phone);
          const badge = getBadge(contact.status);
          const relativeTime = formatRelativeTime(contact.lastMessageAt);

          return (
            <button
              type="button"
              key={contact.id}
              className={`wa-contact-item ${isActive ? 'active' : ''}`}
              onClick={() => {
                onSelectContact(contact.id);
                if (window.innerWidth <= 900) {
                  onToggleSidebar();
                }
              }}
            >
              <div className="wa-contact-main">
                <Avatar name={contact.name} avatarUrl={contact.avatarUrl} phone={contact.phone} />

                <div className="wa-contact-body">
                  <div className="wa-contact-row">
                    <strong>{displayName}</strong>
                    <span className="wa-contact-time">{relativeTime}</span>
                  </div>
                  <p className="wa-contact-preview">{contact.lastMessage || 'Sem mensagens ainda.'}</p>
                  <div className={`wa-contact-badge ${badge.className}`}>{badge.label}</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
