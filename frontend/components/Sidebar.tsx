import Avatar from './Avatar';
import { Contact } from '../lib/types';

type SidebarProps = {
  contacts: Contact[];
  selectedContactId: string;
  onSelectContact: (contactId: string) => void;
};

export default function Sidebar({ contacts, selectedContactId, onSelectContact }: SidebarProps) {
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
    <aside className="wa-sidebar">
      <header className="wa-sidebar-header">
        <h2>Atendimentos</h2>
      </header>

      <div className="wa-contact-list">
        {contacts.map((contact) => {
          const isActive = contact.id === selectedContactId;
          const displayName = contact.name || formatPhone(contact.phone);

          return (
            <button
              type="button"
              key={contact.id}
              className={`wa-contact-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelectContact(contact.id)}
            >
              <div className="wa-contact-main">
                <Avatar name={contact.name} avatarUrl={contact.avatarUrl} phone={contact.phone} />

                <div className="wa-contact-body">
                  <div className="wa-contact-row">
                    <strong>{displayName}</strong>
                  </div>
                  <p>{contact.lastMessage}</p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
