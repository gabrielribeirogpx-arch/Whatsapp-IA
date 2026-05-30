import { ReactNode } from 'react';
import SettingsSidebar, { SettingsTabId } from './SettingsSidebar';

type SettingsLayoutProps = {
  activeTab: SettingsTabId;
  onTabChange: (tab: SettingsTabId) => void;
  children: ReactNode;
};

export default function SettingsLayout({ activeTab, onTabChange, children }: SettingsLayoutProps) {
  return (
    <section className='w-full min-w-0 px-3 py-3 sm:px-4 sm:py-4 lg:px-5'>
      <div className='flex w-full min-w-0 flex-col gap-4'>
        <SettingsSidebar activeTab={activeTab} onTabChange={onTabChange} />
        <div className='min-w-0'>{children}</div>
      </div>
    </section>
  );
}
