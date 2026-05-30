import { ReactNode } from 'react';
import SettingsSidebar, { SettingsTabId } from './SettingsSidebar';

type SettingsLayoutProps = {
  activeTab: SettingsTabId;
  onTabChange: (tab: SettingsTabId) => void;
  children: ReactNode;
};

export default function SettingsLayout({ activeTab, onTabChange, children }: SettingsLayoutProps) {
  return (
    <section className='w-full min-w-0 px-4 py-4 sm:px-6 lg:px-8'>
      <div className='mx-auto flex w-full max-w-7xl flex-col gap-4'>
        <div className='grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]'>
          <SettingsSidebar activeTab={activeTab} onTabChange={onTabChange} />
          <div className='min-w-0'>{children}</div>
        </div>
      </div>
    </section>
  );
}
