import { Bell, CreditCard, KeyRound, LockKeyhole, ShieldCheck, User, UsersRound, type LucideIcon } from 'lucide-react';

export type SettingsTabId = 'profile' | 'preferences' | 'users' | 'permissions' | 'security' | 'apikeys' | 'billing';

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
    title: 'Conta',
    items: [
      { id: 'profile', label: 'Meu Perfil', description: 'Identidade, avatar e dados pessoais', icon: User },
      { id: 'preferences', label: 'Preferências', description: 'Notificações e experiência', icon: Bell }
    ]
  },
  {
    title: 'Workspace/Admin',
    items: [
      { id: 'users', label: 'Usuários', description: 'Convites, seats e gestão do time', icon: UsersRound },
      { id: 'permissions', label: 'Permissões', description: 'Papéis, áreas e políticas de acesso', icon: ShieldCheck },
      { id: 'security', label: 'Segurança', description: 'Sessões, SSO e hardening', icon: LockKeyhole },
      { id: 'apikeys', label: 'API Keys', description: 'Tokens, Meta Cloud API e webhooks', icon: KeyRound, badge: 'Ativo' }
    ]
  },
  {
    title: 'Sistema',
    items: [
      { id: 'billing', label: 'Billing', description: 'Plano, faturas, limites e add-ons', icon: CreditCard }
    ]
  }
];

export const settingsTabIds = settingsNavGroups.flatMap(group => group.items.map(item => item.id));

export default function SettingsSidebar({ activeTab, onTabChange }: { activeTab: SettingsTabId; onTabChange: (tab: SettingsTabId) => void }) {
  return (
    <aside className='sticky top-5 h-fit overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-white/95 p-3 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)] backdrop-blur'>
      <div className='border-b border-slate-100 px-3 pb-3 pt-2'>
        <p className='text-xs font-semibold uppercase tracking-[0.18em] text-slate-400'>Configurações</p>
        <p className='mt-1 text-sm text-slate-600'>Escolha uma área sem sair do hub.</p>
      </div>
      <nav className='mt-3 space-y-4'>
        {settingsNavGroups.map(group => (
          <div key={group.title}>
            <p className='px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400'>{group.title}</p>
            <div className='space-y-1'>
              {group.items.map(({ id, label, description, icon: Icon, badge }) => {
                const selected = activeTab === id;
                return (
                  <button
                    key={id}
                    type='button'
                    onClick={() => onTabChange(id)}
                    className={`group flex w-full items-start gap-3 rounded-2xl px-3 py-3 text-left transition-all duration-200 ${selected ? 'bg-slate-950 text-white shadow-lg shadow-slate-950/15' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'}`}
                  >
                    <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border ${selected ? 'border-white/10 bg-white/10 text-emerald-200' : 'border-slate-200 bg-white text-slate-500 group-hover:text-emerald-600'}`}>
                      <Icon size={17} />
                    </span>
                    <span className='min-w-0 flex-1'>
                      <span className='flex items-center gap-2 text-sm font-semibold'>
                        {label}
                        {badge && <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${selected ? 'bg-emerald-300/15 text-emerald-100' : 'bg-emerald-50 text-emerald-700'}`}>{badge}</span>}
                      </span>
                      <span className={`mt-0.5 block text-xs leading-snug ${selected ? 'text-slate-300' : 'text-slate-500'}`}>{description}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
