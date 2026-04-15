import Avatar from './Avatar';
import { IconClose, IconMenu } from './icons';
import { Contact } from '../lib/types';

type SidebarProps = {
  contacts: Contact[];
  selectedContactId: string;
  onSelectContact: (contactId: string) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
};

export default function Sidebar({
  contacts,
  selectedContactId,
  onSelectContact,
  sidebarOpen,
  onToggleSidebar
}: SidebarProps) {
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
        {contacts.map((contact) => {
          const isActive = contact.id === selectedContactId;
          const displayName = contact.name || formatPhone(contact.phone);
          const statusText = contact.isTyping ? 'digitando' : 'online';

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
                    <span className={`wa-contact-status ${contact.isTyping ? 'typing' : 'online'}`}>{statusText}</span>
                  </div>
                  <p>{contact.lastMessage || 'Sem mensagens ainda.'}</p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
