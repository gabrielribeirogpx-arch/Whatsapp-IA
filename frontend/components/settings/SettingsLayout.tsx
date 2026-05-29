import { ReactNode } from 'react';
import SettingsSidebar, { SettingsTabId } from './SettingsSidebar';

type SettingsLayoutProps = {
  activeTab: SettingsTabId;
  onTabChange: (tab: SettingsTabId) => void;
  children: ReactNode;
};

export default function SettingsLayout({ activeTab, onTabChange, children }: SettingsLayoutProps) {
  return (
    <section className='w-full min-w-0 px-4 py-6 sm:px-6 lg:px-8'>
      <div className='mx-auto flex w-full max-w-7xl flex-col gap-5'>
        <header className='relative overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-gradient-to-br from-slate-950 via-slate-900 to-emerald-950 p-6 text-white shadow-[0_24px_60px_-38px_rgba(2,6,23,0.9)] md:p-8'>
          <div className='pointer-events-none absolute -right-16 -top-16 h-44 w-44 rounded-full bg-emerald-400/20 blur-3xl' />
          <div className='pointer-events-none absolute bottom-0 left-1/3 h-24 w-24 rounded-full bg-cyan-300/10 blur-2xl' />
          <p className='inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-semibold text-emerald-100 shadow-sm backdrop-blur'>Settings Hub</p>
          <div className='mt-4 flex flex-wrap items-center gap-3'>
            <h1 className='text-2xl font-semibold tracking-tight md:text-[1.9rem]'>Administração do workspace</h1>
            <span className='rounded-full border border-emerald-300/30 bg-emerald-300/10 px-3 py-1 text-xs font-semibold text-emerald-100'>Enterprise Control Center</span>
          </div>
          <p className='mt-2 max-w-3xl text-sm leading-relaxed text-slate-300'>Centralize usuários, permissões, API Keys, integrações e billing em um hub administrativo separado da conta do usuário.</p>
        </header>

        <div className='grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-[280px_minmax(0,1fr)]'>
          <SettingsSidebar activeTab={activeTab} onTabChange={onTabChange} />
          <div className='min-w-0'>{children}</div>
        </div>
      </div>
    </section>
  );
}
