'use client';

import { useEffect, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import SettingsContent from '@/components/settings/SettingsContent';
import SettingsLayout from '@/components/settings/SettingsLayout';
import { SettingsTabId, settingsTabIds } from '@/components/settings/SettingsSidebar';

const DEFAULT_TAB: SettingsTabId = 'whatsapp-business';
const DEFAULT_WHATSAPP_SECTION = 'overview';
const whatsappSections = ['overview', 'connections', 'templates', 'api-keys', 'webhooks'] as const;
type WhatsAppSection = typeof whatsappSections[number];

export default function SettingsPageClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const requestedTab = searchParams.get('tab');
  const requestedSection = searchParams.get('section');

  const activeTab = useMemo<SettingsTabId>(() => (
    settingsTabIds.includes(requestedTab as SettingsTabId) ? requestedTab as SettingsTabId : DEFAULT_TAB
  ), [requestedTab]);
  const activeWhatsAppSection = useMemo<WhatsAppSection>(() => (
    whatsappSections.includes(requestedSection as WhatsAppSection)
      ? requestedSection as WhatsAppSection
      : DEFAULT_WHATSAPP_SECTION
  ), [requestedSection]);

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

  const handleWhatsAppSectionChange = (section: WhatsAppSection) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set('tab', 'whatsapp-business');
    nextParams.set('section', section);
    router.push(`${pathname}?${nextParams.toString()}`);
  };

  return (
    <SettingsLayout activeTab={activeTab} onTabChange={handleTabChange}>
      <SettingsContent activeTab={activeTab} whatsAppSection={activeWhatsAppSection} onWhatsAppSectionChange={handleWhatsAppSectionChange} />
    </SettingsLayout>
  );
}
