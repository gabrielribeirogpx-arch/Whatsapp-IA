'use client';

import Link from 'next/link';
import { BarChart3, BookOpen, Cable, Contact, Megaphone, Package, Settings, ShieldCheck, Sparkles } from 'lucide-react';
import { MobileBottomSheet } from './MobileBottomSheet';

const items = [
  ['Campanhas', '/dashboard/campaigns', Megaphone], ['Contatos', '/dashboard/contacts', Contact], ['Relatórios', '/dashboard/campaigns/reports', BarChart3], ['Produtos', '/dashboard/products', Package], ['Integrações', '/dashboard/settings', Cable], ['Configurações', '/dashboard/settings', Settings], ['IA', '/dashboard/ai/playground', Sparkles], ['Segurança', '/dashboard/security/audit', ShieldCheck], ['Documentação', '/dashboard/knowledge', BookOpen],
] as const;
export function MobileMoreMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
 return <MobileBottomSheet open={open} onClose={onClose} title="Mais">
   <nav className="mobile-more-menu" aria-label="Outros módulos">{items.map(([label, href, Icon]) => <Link key={href + label} href={href} onClick={onClose}><Icon size={20} aria-hidden="true" /><span>{label}</span></Link>)}</nav>
 </MobileBottomSheet>;
}
