import { Contact } from '../lib/types';

type SidebarProps = {
  contacts: Contact[];
  selectedContactId: string;
  onSelectContact: (contactId: string) => void;
};

export default function Sidebar({ contacts, selectedContactId, onSelectContact }: SidebarProps) {
  return (
    <aside className="wa-sidebar">
      <header className="wa-sidebar-header">
        <h2>Atendimentos</h2>
      </header>

      <div className="wa-contact-list">
        {contacts.map((contact) => {
          const isActive = contact.id === selectedContactId;

          return (
            <button
              type="button"
              key={contact.id}
              className={`wa-contact-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelectContact(contact.id)}
            >
              <div className="wa-contact-row">
                <strong>{contact.name}</strong>
                <span>{contact.phone}</span>
              </div>
              <p>{contact.lastMessage}</p>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
