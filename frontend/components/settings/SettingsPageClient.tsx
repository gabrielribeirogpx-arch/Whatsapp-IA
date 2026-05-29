'use client';

import { useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import SettingsContent from '@/components/settings/SettingsContent';
import SettingsLayout from '@/components/settings/SettingsLayout';
import { SettingsTabId, settingsTabIds } from '@/components/settings/SettingsSidebar';

const DEFAULT_TAB: SettingsTabId = 'profile';

export default function SettingsPageClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const activeTab = useMemo<SettingsTabId>(() => {
    const requestedTab = searchParams.get('tab');
    return settingsTabIds.includes(requestedTab as SettingsTabId) ? requestedTab as SettingsTabId : DEFAULT_TAB;
  }, [searchParams]);

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
