import type { LucideIcon } from 'lucide-react';
import {
  BarChart3, Bot, Boxes, BrainCircuit, BookOpen, Cable, Contact,
  LayoutDashboard, MessageCircle, Package, PanelsTopLeft, Settings,
  ShieldCheck, Sparkles, Users,
} from 'lucide-react';

export type MobileNavigationItem = {
  label: string;
  mobileTitle: string;
  href: string;
  icon: LucideIcon;
  /** Route roots intentionally mirror the desktop sidebar's active paths. */
  matchPaths: string[];
  showInBottomNav?: boolean;
  showInMoreMenu?: boolean;
  description?: string;
};

export const mobileNavigation: MobileNavigationItem[] = [
  { label: 'Início', mobileTitle: 'Início', href: '/dashboard', icon: LayoutDashboard, matchPaths: ['/dashboard'], showInBottomNav: true },
  { label: 'Conversas', mobileTitle: 'Conversas', href: '/dashboard/inbox', icon: MessageCircle, matchPaths: ['/dashboard/inbox'], showInBottomNav: true },
  { label: 'CRM', mobileTitle: 'CRM', href: '/dashboard/pipeline', icon: PanelsTopLeft, matchPaths: ['/dashboard/pipeline', '/dashboard/contacts', '/dashboard/clients'], showInBottomNav: true },
  { label: 'Fluxos', mobileTitle: 'Fluxos', href: '/dashboard/flows', icon: Bot, matchPaths: ['/dashboard/flows', '/dashboard/flow-builder'], showInBottomNav: true },
  { label: 'Campanhas', mobileTitle: 'Campanhas', href: '/dashboard/campaigns', icon: Sparkles, matchPaths: ['/dashboard/campaigns'], showInMoreMenu: true },
  { label: 'Contatos', mobileTitle: 'Contatos', href: '/dashboard/contacts', icon: Contact, matchPaths: ['/dashboard/contacts'], showInMoreMenu: true },
  { label: 'Relatórios', mobileTitle: 'Relatórios', href: '/dashboard/campaigns/reports', icon: BarChart3, matchPaths: ['/dashboard/campaigns/reports'], showInMoreMenu: true },
  { label: 'Tarefas', mobileTitle: 'Tarefas', href: '/dashboard/tasks', icon: Users, matchPaths: ['/dashboard/tasks'], showInMoreMenu: true },
  { label: 'Produtos', mobileTitle: 'Produtos', href: '/dashboard/products', icon: Package, matchPaths: ['/dashboard/products'], showInMoreMenu: true },
  { label: 'Base de conhecimento', mobileTitle: 'Base de conhecimento', href: '/dashboard/knowledge', icon: BookOpen, matchPaths: ['/dashboard/knowledge'], showInMoreMenu: true },
  { label: 'IA', mobileTitle: 'Inteligência artificial', href: '/dashboard/ai/playground', icon: BrainCircuit, matchPaths: ['/dashboard/ai', '/dashboard/ai-settings'], showInMoreMenu: true },
  { label: 'MCP', mobileTitle: 'MCP', href: '/dashboard/ai/mcp', icon: Cable, matchPaths: ['/dashboard/ai/mcp'], showInMoreMenu: true },
  { label: 'Configurações', mobileTitle: 'Configurações', href: '/dashboard/settings', icon: Settings, matchPaths: ['/dashboard/settings', '/dashboard/account'], showInMoreMenu: true },
  { label: 'Segurança', mobileTitle: 'Segurança', href: '/dashboard/security/audit', icon: ShieldCheck, matchPaths: ['/dashboard/security'], showInMoreMenu: true },
  { label: 'Clientes', mobileTitle: 'Clientes', href: '/dashboard/clients', icon: Boxes, matchPaths: ['/dashboard/clients'], showInMoreMenu: true },
];

export function matchesMobileNavigation(pathname: string, item: MobileNavigationItem) {
  return item.matchPaths.some((path) => path === '/dashboard'
    ? pathname === path
    : pathname === path || pathname.startsWith(`${path}/`));
}

export function getMobilePageMeta(pathname: string) {
  if (pathname.startsWith('/dashboard/contacts/')) return { title: 'Contato', backHref: '/dashboard/contacts' };
  if (pathname.startsWith('/dashboard/flow-builder')) return { title: 'Editor de fluxo', backHref: '/dashboard/flows' };
  const item = mobileNavigation.find((candidate) => matchesMobileNavigation(pathname, candidate));
  return { title: item?.mobileTitle ?? 'Início' };
}
