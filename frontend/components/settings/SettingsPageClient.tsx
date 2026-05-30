'use client';

import { useEffect, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import SettingsContent from '@/components/settings/SettingsContent';
import SettingsLayout from '@/components/settings/SettingsLayout';
import { SettingsTabId, settingsTabIds } from '@/components/settings/SettingsSidebar';

const DEFAULT_TAB: SettingsTabId = 'whatsapp-business';

export default function SettingsPageClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const requestedTab = searchParams.get('tab');

  const activeTab = useMemo<SettingsTabId>(() => (
    settingsTabIds.includes(requestedTab as SettingsTabId) ? requestedTab as SettingsTabId : DEFAULT_TAB
  ), [requestedTab]);

  useEffect(() => {
    if (!requestedTab || settingsTabIds.includes(requestedTab as SettingsTabId)) return;

    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set('tab', DEFAULT_TAB);
    router.replace(`${pathname}?${nextParams.toString()}`, { scroll: false });
  }, [pathname, requestedTab, router, searchParams]);

  const handleTabChange = (tab: SettingsTabId) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set('tab', tab);
    router.push(`${pathname}?${nextParams.toString()}`);
  };

  return (
    <SettingsLayout activeTab={activeTab} onTabChange={handleTabChange}>
      <SettingsContent activeTab={activeTab} />
    </SettingsLayout>
  );
}
