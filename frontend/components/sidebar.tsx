import { Conversation, TenantSession } from '../lib/types';

type SidebarProps = {
  session: TenantSession;
  conversations: Conversation[];
  selectedPhone: string;
  onSelectConversation: (phone: string) => void;
  onLogout: () => void;
};

export default function Sidebar({
  session,
  conversations,
  selectedPhone,
  onSelectConversation,
  onLogout
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <div>
          <h2>{session.name}</h2>
          <p>
            Plano {session.usage.plan} · {session.usage.messages_used_month}/{session.usage.max_monthly_messages}
          </p>
        </div>
        <button type="button" className="ghost-button" onClick={onLogout}>
          Sair
        </button>
      </header>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <p className="empty-state">Nenhuma conversa encontrada.</p>
        ) : null}

        {conversations.map((conversation) => {
          const isActive = conversation.phone === selectedPhone;
          const statusLabel = conversation.status === 'human' ? 'Humano' : 'IA';

          return (
            <button
              type="button"
              key={conversation.phone}
              className={`conversation-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelectConversation(conversation.phone)}
            >
              <div className="conversation-row">
                <strong>{conversation.name || conversation.phone}</strong>
                <span className={`status-badge ${conversation.status === 'human' ? 'human' : ''}`}>{statusLabel}</span>
              </div>
              <p>{conversation.last_message || 'Sem mensagens ainda'}</p>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
