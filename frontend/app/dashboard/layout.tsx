'use client';

import Link from 'next/link';
import { ReactNode } from 'react';
import { usePathname } from 'next/navigation';

function FlowAnalyticsSidebar({ flowId }: { flowId?: string }) {
  const flowPath = flowId ? `/dashboard/flows/${flowId}` : '/dashboard/flows';
  const analyticsPath = flowId ? `/dashboard/flows/${flowId}/analytics` : '/dashboard/flows';

  return (
    <nav className="dash-sidebar">
      <div className="dash-sidebar-logo">
        <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
        <img src="/Logo2.svg" alt="Logo" className="logo-full" />
      </div>

      <span className="dash-nav-section">Flow Analytics</span>

      <Link href="/dashboard/flows" className="dash-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
        <span className="dash-nav-label">Todos os Flows</span>
      </Link>

      <Link href={flowPath} className="dash-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        <span className="dash-nav-label">Voltar ao Flow</span>
      </Link>

      <Link href={analyticsPath} className="dash-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"/><rect x="7" y="13" width="3" height="5"/><rect x="12" y="9" width="3" height="9"/><rect x="17" y="6" width="3" height="12"/></svg>
        <span className="dash-nav-label">Analytics</span>
      </Link>
    </nav>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isFlowBuilder = pathname.startsWith('/dashboard/flow-builder');
  const isFlowAnalytics = pathname.includes('/dashboard/flows/') && pathname.endsWith('/analytics');

  const pathnameSegments = pathname.split('/');
  const flowsIndex = pathnameSegments.indexOf('flows');
  const flowId = flowsIndex !== -1 ? pathnameSegments[flowsIndex + 1] : undefined;

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#F7F8F7', fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {!isFlowBuilder && !isFlowAnalytics && (
        <nav className="dash-sidebar">
          <div className="dash-sidebar-logo">
            <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
            <img src="/Logo2.svg" alt="Logo" className="logo-full" />
          </div>

          <span className="dash-nav-section">Principal</span>

          <Link href="/dashboard" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
            <span className="dash-nav-label">Dashboard</span>
          </Link>

          <Link href="/chat" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span className="dash-nav-label">Inbox</span>
          </Link>

          <Link href="/crm" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            <span className="dash-nav-label">Clientes</span>
          </Link>

          <Link href="/pipeline" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            <span className="dash-nav-label">Pipeline</span>
          </Link>

          <div className="dash-nav-divider" />
          <span className="dash-nav-section">Ferramentas</span>

          <Link href="/products" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
            <span className="dash-nav-label">Produtos</span>
          </Link>

          <Link href="/knowledge" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
            <span className="dash-nav-label">Knowledge</span>
          </Link>

          <Link href="/dashboard/flow-builder" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            <span className="dash-nav-label">Flow Builder</span>
          </Link>

          <Link href="/dashboard/settings" className="dash-nav-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            <span className="dash-nav-label">Configurações</span>
          </Link>
        </nav>
      )}

      {isFlowAnalytics && !isFlowBuilder && <FlowAnalyticsSidebar flowId={flowId} />}

      <main style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: isFlowBuilder || isFlowAnalytics ? '0' : '32px 24px 32px 16px' }}>{children}</main>
    </div>
  );
}
