'use client';

import Link from 'next/link';
import { ReactNode, Suspense, useEffect, useLayoutEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { deleteFlow, duplicateFlow, listFlows, updateFlowStatus } from '@/lib/api';
import SidebarUserProfile from '@/components/SidebarUserProfile';
import { dashboardSidebarSections, isDashboardSidebarItemActive } from '@/components/dashboard/sidebar-items';
import { AppShell } from '@/components/layout/AppShell';
import { OnboardingProvider } from '@/components/onboarding/OnboardingProvider';
import { getMobilePageMeta } from '@/components/layout/mobile-navigation';

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
    if (!window.confirm('Deseja excluir este fluxo?')) return;
    await deleteFlow(flowId);
    router.push('/dashboard/flows');
  };

  return (
    <div className={`dash-sidebar ${expanded ? 'is-expanded' : ''}`}>
      <div className="dash-sidebar-logo">
        <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
        <img src="/Logo2.svg" alt="Logo" className="logo-full" />
      </div>

      <nav className="dash-sidebar-scroll-area" aria-label="Menu de fluxos">
        <span className="dash-nav-section">Fluxos</span>

        <button type="button" className="dash-nav-item" onClick={() => router.push('/dashboard/flows')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          <span className="dash-nav-label">Todos os Fluxos</span>
        </button>

        <button type="button" className="dash-nav-item" onClick={() => flowId && router.push(`/dashboard/flow-builder?flow_id=${flowId}`)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="12" cy="19" r="2"/><line x1="7" y1="6.5" x2="10.5" y2="16.5"/><line x1="17" y1="6.5" x2="13.5" y2="16.5"/></svg>
          <span className="dash-nav-label">Abrir builder</span>
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
          <span className="dash-nav-label">{isActive ? 'Desativar fluxo' : 'Ativar fluxo'}</span>
        </button>

        <button type="button" className="dash-nav-item" onClick={handleDelete}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          <span className="dash-nav-label">Excluir</span>
        </button>
      </nav>

      <div className="dash-sidebar-footer">
        <SidebarUserProfile expanded={expanded} />
      </div>
    </div>
  );
}

function DashboardSidebar({ expanded }: { expanded: boolean }) {
  const pathname = usePathname();

  return (
    <div className={`dash-sidebar ${expanded ? 'is-expanded' : ''}`}>
      <div className="dash-sidebar-logo">
        <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
        <img src="/Logo2.svg" alt="Logo" className="logo-full" />
      </div>

      <nav className="dash-sidebar-scroll-area" aria-label="Menu principal">
        {dashboardSidebarSections.map((section, sectionIndex) => (
          <div key={section.label}>
            {sectionIndex > 0 ? <div className="dash-nav-divider" /> : null}
            <span className="dash-nav-section">{section.label}</span>
            {section.items.map((item) => {
            const active = isDashboardSidebarItemActive(pathname, item);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`dash-nav-item ${active ? 'active' : ''}`}
                aria-current={active ? 'page' : undefined}
              >
                {item.icon}
                <span className="dash-nav-label">{item.label}</span>
              </Link>
            );
            })}
          </div>
        ))}
      </nav>

      <div className="dash-sidebar-footer">
        <SidebarUserProfile expanded={expanded} />
      </div>
    </div>
  );
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.title = 'Wazza API Dashboard';
  }, []);

  const pathname = usePathname();
  const isFlowBuilder = pathname.startsWith('/dashboard/flow-builder');
  const isFlowAnalytics = pathname.includes('/dashboard/flows/') && pathname.endsWith('/analytics');
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [campaignWizardFullscreen, setCampaignWizardFullscreen] = useState(false);

  useLayoutEffect(() => {
    const syncCampaignWizardState = () => {
      setCampaignWizardFullscreen(document.body.classList.contains('campaign-wizard-fullscreen-open'));
    };
    const handleCampaignWizardState = (event: Event) => {
      const detail = (event as CustomEvent<{ open?: boolean }>).detail;
      setCampaignWizardFullscreen(Boolean(detail?.open));
    };

    syncCampaignWizardState();
    window.addEventListener('campaign-wizard-fullscreen', handleCampaignWizardState);
    return () => {
      window.removeEventListener('campaign-wizard-fullscreen', handleCampaignWizardState);
    };
  }, []);

  const pathnameSegments = pathname.split('/');
  const flowsIndex = pathnameSegments.indexOf('flows');
  const flowId = flowsIndex !== -1 ? pathnameSegments[flowsIndex + 1] : undefined;
  const mobileMeta = getMobilePageMeta(pathname);

  return (
    <OnboardingProvider>
    {!campaignWizardFullscreen && <div className="dashboard-mobile-shell"><Suspense fallback={null}><AppShell title={mobileMeta.title} backHref={mobileMeta.backHref}>{children}</AppShell></Suspense></div>}
    <div className={`dashboard-desktop-shell flex min-h-screen bg-[#F8FAFC] transition-[padding,margin] duration-300 ease-out ${campaignWizardFullscreen ? 'dashboard-layout--campaign-fullscreen' : ''}`} style={{ fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {!campaignWizardFullscreen && !isFlowBuilder && !isFlowAnalytics && (
        <aside
          className={`flex-shrink-0 transition-all duration-300 ease-out ${sidebarExpanded ? 'w-[200px]' : 'w-[56px]'}`}
          onMouseEnter={() => setSidebarExpanded(true)}
          onMouseLeave={() => setSidebarExpanded(false)}
        >
          <DashboardSidebar expanded={sidebarExpanded} />
        </aside>
      )}

      {!campaignWizardFullscreen && isFlowAnalytics && !isFlowBuilder && (
        <aside
          className={`flex-shrink-0 transition-all duration-300 ease-out ${sidebarExpanded ? 'w-[200px]' : 'w-[56px]'}`}
          onMouseEnter={() => setSidebarExpanded(true)}
          onMouseLeave={() => setSidebarExpanded(false)}
        >
          <FlowAnalyticsSidebar flowId={flowId} expanded={sidebarExpanded} />
        </aside>
      )}

      <main data-onboarding-target="workspace" className={`wazza-desktop-main min-w-0 flex-1 overflow-y-auto transition-all duration-300 ease-out ${campaignWizardFullscreen ? 'w-screen max-w-none basis-full' : ''}`}>
        {children}
      </main>
    </div>
    </OnboardingProvider>
  );
}
