import { KanbanSquare, MessageSquareText, type LucideIcon } from 'lucide-react';

export type SettingsTabId = 'whatsapp-business' | 'pipeline';

type SettingsNavItem = {
  id: SettingsTabId;
  label: string;
  description: string;
  icon: LucideIcon;
  badge?: string;
};

type SettingsNavGroup = {
  title: string;
  items: SettingsNavItem[];
};

export const settingsNavGroups: SettingsNavGroup[] = [
  {
    title: 'Configurações',
    items: [
      { id: 'whatsapp-business', label: 'WhatsApp', description: 'Canal, conexões e templates', icon: MessageSquareText, badge: 'Ativo' },
      { id: 'pipeline', label: 'Pipeline', description: 'Etapas do CRM', icon: KanbanSquare, badge: 'Sprint 1' }
    ]
  }
];

export const settingsTabIds = settingsNavGroups.flatMap(group => group.items.map(item => item.id));

export default function SettingsSidebar({ activeTab, onTabChange }: { activeTab: SettingsTabId; onTabChange: (tab: SettingsTabId) => void }) {
  const items = settingsNavGroups.flatMap(group => group.items);

  return (
    <nav
      className='sticky top-0 z-10 -mx-3 border-b border-[color:var(--surface-border)] bg-[#F8FAFC]/95 px-3 py-2 backdrop-blur sm:-mx-4 sm:px-4 lg:-mx-5 lg:px-5'
      aria-label='Configurações'
    >
      <div className='flex min-w-0 items-center gap-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'>
        {items.map(({ id, label, icon: Icon }) => {
          const selected = activeTab === id;
          return (
            <button
              key={id}
              type='button'
              onClick={() => onTabChange(id)}
              aria-current={selected ? 'page' : undefined}
              className={`inline-flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-semibold leading-none transition-all duration-200 sm:px-4 ${selected ? 'border-slate-950 bg-slate-950 text-white shadow-sm shadow-slate-950/10' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950'}`}
            >
              <Icon size={16} />
              <span>{label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
