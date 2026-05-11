import React from "react";

export default function CampaignRecipientsTable(props: any) {
  return <div className="rounded-xl border border-zinc-200 bg-white/90 p-4 shadow-sm">{props?.children ?? null}</div>;
}
