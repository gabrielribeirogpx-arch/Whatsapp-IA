import { ReactNode } from 'react';
import AccountSidebar, { AccountTabId } from './AccountSidebar';

type AccountLayoutProps = {
  activeTab: AccountTabId;
  onTabChange: (tab: AccountTabId) => void;
  children: ReactNode;
};

export default function AccountLayout({ activeTab, onTabChange, children }: AccountLayoutProps) {
  return (
    <section className='w-full min-w-0 px-4 py-5 sm:px-6 lg:px-8'>
      <div className='mx-auto flex w-full max-w-7xl flex-col gap-4'>
        <div className='grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]'>
          <AccountSidebar activeTab={activeTab} onTabChange={onTabChange} />
          <div className='min-w-0'>{children}</div>
        </div>
      </div>
    </section>
  );
}
