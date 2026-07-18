import type { ReactNode } from "react";

export type DashboardSidebarItem = {
  href: string;
  label: string;
  icon: ReactNode;
  exact?: boolean;
  activePaths?: string[];
};

export type DashboardSidebarSection = {
  label: string;
  items: DashboardSidebarItem[];
};

const iconProps = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: "2",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const dashboardSidebarSections: DashboardSidebarSection[] = [
  {
    label: "Principal",
    items: [
      {
        href: "/dashboard",
        label: "Dashboard",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <rect x="3" y="3" width="7" height="7" />
            <rect x="14" y="3" width="7" height="7" />
            <rect x="3" y="14" width="7" height="7" />
            <rect x="14" y="14" width="7" height="7" />
          </svg>
        ),
      },
      {
        href: "/dashboard/inbox",
        label: "Inbox",
        icon: (
          <svg {...iconProps}>
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        ),
      },
      {
        href: "/dashboard/clients",
        label: "Clientes",
        icon: (
          <svg {...iconProps}>
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        ),
      },
      {
        href: "/dashboard/pipeline",
        label: "Pipeline",
        icon: (
          <svg {...iconProps}>
            <line x1="18" y1="20" x2="18" y2="10" />
            <line x1="12" y1="20" x2="12" y2="4" />
            <line x1="6" y1="20" x2="6" y2="14" />
          </svg>
        ),
      },
      {
        href: "/dashboard/tasks",
        label: "Tarefas",
        icon: (
          <svg {...iconProps}>
            <rect x="3" y="4" width="18" height="17" rx="2" />
            <path d="M8 2h8v4H8z" />
            <path d="M8 11h8" />
            <path d="M8 16h5" />
          </svg>
        ),
      },
      {
        href: "/dashboard/campaigns",
        label: "Campanhas",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <path d="M3 11l18-5-5 18-2-7-7-2z" />
          </svg>
        ),
      },
      {
        href: "/dashboard/contacts",
        label: "Contatos",
        icon: (
          <svg {...iconProps}>
            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="8.5" cy="7" r="4" />
            <line x1="20" y1="8" x2="20" y2="14" />
            <line x1="23" y1="11" x2="17" y2="11" />
          </svg>
        ),
      },
    ],
  },
  {
    label: "Ferramentas",
    items: [
      {
        href: "/dashboard/products",
        label: "Produtos",
        icon: (
          <svg {...iconProps}>
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
          </svg>
        ),
      },
      {
        href: "/dashboard/knowledge",
        label: "Base de conhecimento",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
          </svg>
        ),
      },
      {
        href: "/dashboard/ai-settings",
        label: "IA Configurações",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <path d="M12 3l1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5z" />
            <path d="M19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z" />
          </svg>
        ),
      },
      {
        href: "/dashboard/ai/playground",
        label: "IA Playground",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <path d="M9 3h6" />
            <path d="M10 3v6l-5 9a2 2 0 0 0 1.75 3h10.5A2 2 0 0 0 19 18l-5-9V3" />
            <path d="M8.5 15h7" />
          </svg>
        ),
      },
      {
        href: "/dashboard/ai/memories",
        label: "IA Memórias",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <path d="M9.5 4.5A3.5 3.5 0 0 0 6 8v.5A3.5 3.5 0 0 0 4 15a3.5 3.5 0 0 0 5.5 2.9" />
            <path d="M14.5 4.5A3.5 3.5 0 0 1 18 8v.5a3.5 3.5 0 0 1 2 6.5 3.5 3.5 0 0 1-5.5 2.9" />
            <path d="M9.5 4.5A3.5 3.5 0 0 1 12 6a3.5 3.5 0 0 1 2.5-1.5" />
            <path d="M12 6v15" />
            <path d="M8 11.5h4" />
            <path d="M16 11.5h-4" />
          </svg>
        ),
      },
      {
        href: "/dashboard/ai/mcp",
        label: "Integrações",
        exact: true,
        icon: (
          <svg {...iconProps}>
            <path d="M9 7v5a3 3 0 0 0 6 0V7" />
            <path d="M7 4v3" />
            <path d="M11 4v3" />
            <path d="M15 4v3" />
            <path d="M12 15v5" />
            <path d="M9 20h6" />
          </svg>
        ),
      },
      {
        href: "/dashboard/flows",
        label: "Fluxos",
        activePaths: ["/dashboard/flow-builder"],
        icon: (
          <svg {...iconProps}>
            <circle cx="5" cy="5" r="2" />
            <circle cx="19" cy="5" r="2" />
            <circle cx="12" cy="19" r="2" />
            <line x1="7" y1="6.5" x2="10.5" y2="16.5" />
            <line x1="17" y1="6.5" x2="13.5" y2="16.5" />
          </svg>
        ),
      },
      {
        href: "/dashboard/settings?tab=whatsapp-business",
        label: "Configurações",
        activePaths: ["/dashboard/settings"],
        icon: (
          <svg {...iconProps}>
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        ),
      },
    ],
  },
];

export function isDashboardSidebarItemActive(
  pathname: string,
  item: DashboardSidebarItem,
) {
  const baseHref = item.href.split("?")[0];
  const candidates = [baseHref, ...(item.activePaths || [])];
  return candidates.some((path) =>
    item.exact
      ? pathname === path
      : pathname === path || pathname.startsWith(`${path}/`),
  );
}
