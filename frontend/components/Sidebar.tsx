import { Contact } from '../lib/types';

type SidebarProps = {
  contacts: Contact[];
  selectedContactId: string;
  onSelectContact: (contactId: string) => void;
};

function getAvatar(name: string | null, phone: string) {
  const base = (name || phone || '?').trim();
  const initial = base.charAt(0).toUpperCase();

  const colors = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#3b82f6'];

  const colorIndex = base.length % colors.length;

  return {
    initial,
    color: colors[colorIndex]
  };
}

export default function Sidebar({ contacts, selectedContactId, onSelectContact }: SidebarProps) {
  return (
    <aside className="wa-sidebar">
      <header className="wa-sidebar-header">
        <h2>Atendimentos</h2>
      </header>

      <div className="wa-contact-list">
        {contacts.map((contact) => {
          const isActive = contact.id === selectedContactId;
          const avatar = getAvatar(contact.name, contact.phone);

          return (
            <button
              type="button"
              key={contact.id}
              className={`wa-contact-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelectContact(contact.id)}
            >
              <div className="wa-contact-main">
                {contact.avatarUrl ? (
                  <img src={contact.avatarUrl} alt={`Avatar de ${contact.name || contact.phone}`} className="wa-avatar-image" />
                ) : (
                  <div
                    className="wa-avatar-fallback"
                    style={{
                      backgroundColor: avatar.color
                    }}
                  >
                    {avatar.initial}
                  </div>
                )}

                <div className="wa-contact-body">
                  <div className="wa-contact-row">
                    <strong>{contact.name || contact.phone}</strong>
                    <span>{contact.phone}</span>
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
