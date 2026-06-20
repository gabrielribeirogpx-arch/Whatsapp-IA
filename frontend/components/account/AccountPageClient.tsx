"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import AccountLayout from "@/components/account/AccountLayout";
import {
  AccountTabId,
  accountTabIds,
} from "@/components/account/AccountSidebar";
import SettingsContent from "@/components/settings/SettingsContent";

const DEFAULT_TAB: AccountTabId = "profile";

export default function AccountPageClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const requestedTab = searchParams.get("tab");

  useEffect(() => {
    if (requestedTab === "integrations") {
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.delete("tab");
      const query = nextParams.toString();
      router.replace(
        query ? `/dashboard/ai/mcp?${query}` : "/dashboard/ai/mcp",
      );
    }
  }, [requestedTab, router, searchParams]);

  const activeTab = useMemo<AccountTabId>(() => {
    return accountTabIds.includes(requestedTab as AccountTabId)
      ? (requestedTab as AccountTabId)
      : DEFAULT_TAB;
  }, [requestedTab]);

  const handleTabChange = (tab: AccountTabId) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set("tab", tab);
    router.push(`${pathname}?${nextParams.toString()}`);
  };

  return (
    <AccountLayout activeTab={activeTab} onTabChange={handleTabChange}>
      <SettingsContent activeTab={activeTab} />
    </AccountLayout>
  );
}
