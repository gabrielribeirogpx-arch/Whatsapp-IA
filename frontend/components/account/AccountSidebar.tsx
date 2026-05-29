import { Bell, LockKeyhole, User, type LucideIcon } from 'lucide-react';

export type AccountTabId = 'profile' | 'preferences' | 'security';

type AccountNavItem = {
  id: AccountTabId;
  label: string;
  description: string;
  icon: LucideIcon;
};

export const accountNavItems: AccountNavItem[] = [
  { id: 'profile', label: 'Meu Perfil', description: 'Identidade, avatar e dados pessoais', icon: User },
  { id: 'preferences', label: 'Preferências', description: 'Notificações e experiência individual', icon: Bell },
  { id: 'security', label: 'Segurança', description: 'Sessões, login e proteção da conta', icon: LockKeyhole }
];

export const accountTabIds = accountNavItems.map(item => item.id);

export default function AccountSidebar({ activeTab, onTabChange }: { activeTab: AccountTabId; onTabChange: (tab: AccountTabId) => void }) {
  return (
    <aside className='sticky top-5 h-fit overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-white/95 p-3 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)] backdrop-blur'>
      <div className='border-b border-slate-100 px-3 pb-3 pt-2'>
        <p className='text-xs font-semibold uppercase tracking-[0.18em] text-slate-400'>Conta</p>
        <p className='mt-1 text-sm text-slate-600'>Gerencie sua identidade, preferências e segurança pessoal.</p>
      </div>
      <nav className='mt-3 space-y-1'>
        {accountNavItems.map(({ id, label, description, icon: Icon }) => {
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
                <span className='text-sm font-semibold'>{label}</span>
                <span className={`mt-0.5 block text-xs leading-snug ${selected ? 'text-slate-300' : 'text-slate-500'}`}>{description}</span>
              </span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
