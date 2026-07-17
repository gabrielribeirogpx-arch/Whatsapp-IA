import React from "react";

export default function CampaignCard(props: any) {
  return <div className="rounded-[18px] border border-slate-200 bg-white/90 p-3 shadow-[0_18px_45px_-38px_rgba(15,23,42,0.35)] transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-30px_rgba(15,23,42,0.35)]">{props?.children ?? null}</div>;
}
