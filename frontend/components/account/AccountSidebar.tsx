import {
  Bell,
  CreditCard,
  LockKeyhole,
  ShieldCheck,
  User,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

export type AccountTabId =
  | "profile"
  | "preferences"
  | "security"
  | "users"
  | "permissions"
  | "billing";

type AccountNavItem = {
  id: AccountTabId;
  label: string;
  description: string;
  icon: LucideIcon;
};

type AccountNavGroup = {
  title: string;
  items: AccountNavItem[];
};

export const accountNavGroups: AccountNavGroup[] = [
  {
    title: "Conta",
    items: [
      {
        id: "profile",
        label: "Meu Perfil",
        description: "Identidade, avatar e dados pessoais",
        icon: User,
      },
      {
        id: "preferences",
        label: "Preferências",
        description: "Notificações e experiência individual",
        icon: Bell,
      },
      {
        id: "security",
        label: "Segurança",
        description: "Sessões, login e proteção da conta",
        icon: LockKeyhole,
      },
    ],
  },
  {
    title: "Workspace",
    items: [
      {
        id: "users",
        label: "Usuários",
        description: "Convites, seats e gestão do time",
        icon: UsersRound,
      },
      {
        id: "permissions",
        label: "Permissões",
        description: "Papéis, áreas e políticas de acesso",
        icon: ShieldCheck,
      },
      {
        id: "billing",
        label: "Plano e cobrança",
        description: "Plano, limites e recursos do workspace",
        icon: CreditCard,
      },
    ],
  },
];

export const accountNavItems = accountNavGroups.flatMap((group) => group.items);
export const accountTabIds = accountNavItems.map((item) => item.id);

export default function AccountSidebar({
  activeTab,
  onTabChange,
}: {
  activeTab: AccountTabId;
  onTabChange: (tab: AccountTabId) => void;
}) {
  return (
    <aside className="sticky top-5 h-fit overflow-hidden rounded-2xl border border-slate-200 bg-white p-3">
      <div className="border-b border-slate-200 px-3 pb-3 pt-2">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
          Conta + Workspace
        </p>
        <p className="mt-1 text-sm text-slate-600">
          Gerencie sua conta e a administração do workspace em um só hub.
        </p>
      </div>
      <nav className="mt-3 space-y-4">
        {accountNavGroups.map((group) => (
          <div key={group.title}>
            <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              {group.title}
            </p>
            <div className="space-y-1">
              {group.items.map(({ id, label, description, icon: Icon }) => {
                const selected = activeTab === id;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => onTabChange(id)}
                    aria-current={selected ? "page" : undefined}
                    className={`group relative flex w-full cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-all duration-[180ms] active:scale-[0.98] ${selected ? "border-emerald-200 bg-emerald-50 text-slate-900" : "border-transparent text-slate-600 hover:translate-x-0.5 hover:bg-slate-50 hover:text-slate-900"}`}
                  >
                    {selected && (
                      <span
                        className="absolute inset-y-2 left-0 w-1 rounded-full bg-emerald-500"
                        aria-hidden="true"
                      />
                    )}
                    <span
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white transition-colors duration-[180ms] ${selected ? "text-emerald-600" : "text-slate-500 group-hover:text-slate-700"}`}
                    >
                      <Icon size={17} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="text-sm font-medium leading-5">{label}</span>
                      <span className="mt-0.5 block text-xs leading-snug text-slate-500">
                        {description}
                      </span>
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
