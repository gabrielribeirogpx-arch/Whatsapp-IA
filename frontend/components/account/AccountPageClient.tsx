'use client';

import { useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import AccountLayout from '@/components/account/AccountLayout';
import { AccountTabId, accountTabIds } from '@/components/account/AccountSidebar';
import SettingsContent from '@/components/settings/SettingsContent';

const DEFAULT_TAB: AccountTabId = 'profile';

export default function AccountPageClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const activeTab = useMemo<AccountTabId>(() => {
    const requestedTab = searchParams.get('tab');
    return accountTabIds.includes(requestedTab as AccountTabId) ? requestedTab as AccountTabId : DEFAULT_TAB;
  }, [searchParams]);

  const handleTabChange = (tab: AccountTabId) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set('tab', tab);
    router.push(`${pathname}?${nextParams.toString()}`);
  };

  return (
    <AccountLayout activeTab={activeTab} onTabChange={handleTabChange}>
      <SettingsContent activeTab={activeTab} />
    </AccountLayout>
  );
}
