'use client';

import Link from 'next/link';
import { ReactNode, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { deleteFlow, duplicateFlow, listFlows, updateFlowStatus } from '@/lib/api';

function FlowAnalyticsSidebar({ flowId, expanded }: { flowId?: string; expanded: boolean }) {
  const router = useRouter();
  const [isActive, setIsActive] = useState(false);

  useEffect(() => {
    if (!flowId) return;
    (async () => {
      const flows = await listFlows();
      const flow = flows.find((item) => item.id === flowId);
      if (flow) setIsActive(flow.is_active);
    })();
  }, [flowId]);

  const handleToggle = async () => {
    if (!flowId) return;
    const next = !isActive;
    setIsActive(next);
    try {
      await updateFlowStatus(flowId, next);
    } catch {
      setIsActive(!next);
    }
  };

  const handleDelete = async () => {
    if (!flowId) return;
    if (!window.confirm('Deseja deletar este flow?')) return;
    await deleteFlow(flowId);
    router.push('/dashboard/flows');
  };

  return (
    <nav className={`dash-sidebar ${expanded ? 'is-expanded' : ''}`}>
      <div className="dash-sidebar-logo">
        <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
        <img src="/Logo2.svg" alt="Logo" className="logo-full" />
      </div>

      <span className="dash-nav-section">Flow Analytics</span>

      <button type="button" className="dash-nav-item" onClick={() => router.push('/dashboard/flows')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
        <span className="dash-nav-label">Todos os Flows</span>
      </button>

      <button type="button" className="dash-nav-item" onClick={() => flowId && router.push(`/dashboard/flow-builder?flow_id=${flowId}`)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="12" cy="19" r="2"/><line x1="7" y1="6.5" x2="10.5" y2="16.5"/><line x1="17" y1="6.5" x2="13.5" y2="16.5"/></svg>
        <span className="dash-nav-label">Abrir Builder</span>
      </button>

      <button type="button" className="dash-nav-item" onClick={() => router.push('/dashboard/flows')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
        <span className="dash-nav-label">Editar</span>
      </button>

      <button type="button" className="dash-nav-item" onClick={async () => flowId && await duplicateFlow(flowId)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><rect x="2" y="2" width="13" height="13" rx="2"/></svg>
        <span className="dash-nav-label">Duplicar</span>
      </button>

      <button type="button" className="dash-nav-item" onClick={handleToggle}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v10"/><path d="M18.4 5.6a9 9 0 1 1-12.8 0"/></svg>
        <span className="dash-nav-label" style={{ color: '#16a34a' }}>{isActive ? 'Desativar Flow' : 'Ativar Flow'}</span>
      </button>

      <button type="button" className="dash-nav-item" onClick={handleDelete}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        <span className="dash-nav-label" style={{ color: '#dc2626' }}>Deletar</span>
      </button>
    </nav>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isFlowBuilder = pathname.startsWith('/dashboard/flow-builder');
  const isFlowAnalytics = pathname.includes('/dashboard/flows/') && pathname.endsWith('/analytics');
  const isDashboardActive = pathname === '/dashboard';
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  const pathnameSegments = pathname.split('/');
  const flowsIndex = pathnameSegments.indexOf('flows');
  const flowId = flowsIndex !== -1 ? pathnameSegments[flowsIndex + 1] : undefined;

  return (
    <div className="flex min-h-screen bg-[#F8FAFC]" style={{ fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {!isFlowBuilder && !isFlowAnalytics && (
        <aside
          className={`flex-shrink-0 transition-all duration-300 ease-out ${sidebarExpanded ? 'w-[200px]' : 'w-[56px]'}`}
          onMouseEnter={() => setSidebarExpanded(true)}
          onMouseLeave={() => setSidebarExpanded(false)}
        >
          <nav className={`dash-sidebar ${sidebarExpanded ? 'is-expanded' : ''}`}>
            <div className="dash-sidebar-logo">
              <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
              <img src="/Logo2.svg" alt="Logo" className="logo-full" />
            </div>

            <span className="dash-nav-section">Principal</span>

            <Link
              href="/dashboard"
              className={`dash-nav-item ${isDashboardActive ? 'active' : ''}`}
              aria-current={isDashboardActive ? 'page' : undefined}
            >
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
        </aside>
      )}

      {isFlowAnalytics && !isFlowBuilder && (
        <aside
          className={`flex-shrink-0 transition-all duration-300 ease-out ${sidebarExpanded ? 'w-[200px]' : 'w-[56px]'}`}
          onMouseEnter={() => setSidebarExpanded(true)}
          onMouseLeave={() => setSidebarExpanded(false)}
        >
          <FlowAnalyticsSidebar flowId={flowId} expanded={sidebarExpanded} />
        </aside>
      )}

      <main className="min-w-0 flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
