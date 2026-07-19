import { useMemo, useState } from 'react';
import { Filter, Search } from 'lucide-react';
import { MobileBottomSheet } from './layout/MobileBottomSheet';
import { MobileHeader } from './layout/MobileHeader';
import Avatar from './Avatar';
import { Contact } from '../lib/types';
import { CONVERSATION_FILTERS, ConversationFilterId, matchesConversationFilter } from '../lib/conversationFilters';

type SidebarProps = {
  contacts: Contact[];
  selectedContactId: string;
  onSelectContact: (contactId: string) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  unansweredCount: number;
  humanRequestsCount: number;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
};

export default function Sidebar({
  contacts,
  selectedContactId,
  onSelectContact,
  sidebarOpen,
  onToggleSidebar,
  unansweredCount,
  humanRequestsCount,
  loading = false,
  error = false,
  onRetry,
}: SidebarProps) {
  console.log("[SIDEBAR RECEIVED]", contacts.length);
  console.log("[SIDEBAR FIRST ITEM]", contacts[0]?.id);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeFilter, setActiveFilter] = useState<ConversationFilterId>('all');
  const [filtersOpen, setFiltersOpen] = useState(false);

  const filterChips = CONVERSATION_FILTERS;

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

  function getBadge(status?: string, hasHumanAssignee = false) {
    const normalizedStatus = status?.toLowerCase();

    if (normalizedStatus === 'human') {
      return hasHumanAssignee ? null : { label: '👤 Humano', className: 'human' };
    }

    if (normalizedStatus === 'bot') {
      return { label: '⚙️ Bot', className: 'bot' };
    }

    if (normalizedStatus === 'ai') {
      return { label: '🤖 IA', className: 'ai' };
    }

    return { label: '⏳ Aguardando', className: 'pending' };
  }

  const filteredContacts = useMemo(() => {
    const normalizedSearchTerm = searchTerm.trim().toLowerCase();

    return contacts.filter((contact) => {
      if (!matchesConversationFilter(contact, activeFilter)) return false;

      if (!normalizedSearchTerm) return true;

      const searchFields = [contact.phone, contact.name || '', contact.lastMessage || '', contact.stage || '']
        .join(' ')
        .toLowerCase();

      return searchFields.includes(normalizedSearchTerm);
    });
  }, [contacts, activeFilter, searchTerm]);

  return (
    <aside className={`wa-sidebar ${sidebarOpen ? 'open' : ''}`}>
      <div className="wa-contact-list">
        <div className="wa-mobile-inbox-title">
          <MobileHeader
            title="Inbox"
            showLogo={false}
            action={<button type="button" onClick={() => setFiltersOpen(true)} aria-label="Abrir filtros"><Filter size={20} /><span>{activeFilter !== "all" ? "1" : ""}</span></button>}
          />
        </div>
        <div className="wa-sidebar-search-wrapper">
          <span className="wa-sidebar-search-icon" aria-hidden="true"><Search size={17} /></span>
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
                {chip.label}{chip.id === 'unanswered' && unansweredCount > 0 ? ` (${unansweredCount})` : ''}{chip.id === 'awaiting' && humanRequestsCount > 0 ? ` (${humanRequestsCount})` : ''}
              </button>
            );
          })}
        </div>

        {loading ? <div className="wa-mobile-inbox-skeleton" aria-label="Carregando conversas"><i /><i /><i /><i /><i /></div> : null}
        {!loading && error ? (
          <div className="wa-inbox-retry" role="alert">
            <p>Não foi possível carregar as conversas.</p>
            <button type="button" onClick={onRetry}>Tentar novamente</button>
          </div>
        ) : null}
        {!loading && !error && filteredContacts.length === 0 ? (
          <p className="wa-inbox-empty">Nenhuma conversa encontrada</p>
        ) : null}

        {!loading && filteredContacts.map((contact) => {
          const isActive = contact.id === selectedContactId;
          const displayName = contact.name || formatPhone(contact.phone);
          const assignedUserName = contact.assignedUserName?.trim() || 'Atendente';
          const inHumanCare = Boolean(contact.inHumanCare);
          const badge = getBadge(contact.status, inHumanCare);
          const awaitingHuman = Boolean(contact.awaitingHumanAssignment);
          const relativeTime = formatRelativeTime(contact.lastMessageAt);
          const temp = (contact.score ?? 0) >= 80 ? 'hot' : (contact.score ?? 0) >= 40 ? 'warm' : 'cold';
          const unread = contact.status !== 'human' ? 1 : 0;

          return (
            <button
              type="button"
              key={contact.id}
              className={`wa-contact-item ${isActive ? 'active' : ''}`}
              onClick={() => {
                onSelectContact(contact.id);
                if (window.innerWidth < 1024) {
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
                  <div className="wa-contact-meta">
                    <div className={`wa-contact-temp ${temp}`}>{temp === 'hot' ? 'Quente' : temp === 'warm' ? 'Morno' : 'Frio'}</div>
                    {awaitingHuman ? <div className="wa-contact-badge handoff">🔴 Aguardando Atendente</div> : null}
                    {inHumanCare ? <div className="wa-contact-badge assigned">🟢 Em atendimento por {assignedUserName}</div> : null}
                    {badge ? <div className={`wa-contact-badge ${badge.className}`}>{badge.label}</div> : null}
                    {contact.stage ? <div className="wa-contact-tag">{contact.stage}</div> : null}
                    {unread ? <div className="wa-contact-unread">{unread}</div> : null}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <MobileBottomSheet open={filtersOpen} onClose={() => setFiltersOpen(false)} title="Filtrar conversas">
        <div className="wa-mobile-filter-options" role="list">{filterChips.map((chip) => <button key={chip.id} type="button" className={activeFilter === chip.id ? "active" : ""} onClick={() => { setActiveFilter(chip.id); setFiltersOpen(false); }}>{chip.label}</button>)}</div>
      </MobileBottomSheet>
    </aside>
  );
}
