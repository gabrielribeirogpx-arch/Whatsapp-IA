import { ReactNode } from "react";

type AccountPageHeaderProps = {
  title: string;
  description: string;
  badges?: ReactNode;
  actions?: ReactNode;
};

/**
 * Shared, compact introduction for every Account and Workspace page.
 * Keep page-specific controls in `badges` and `actions` so the visual
 * structure remains consistent as new account tabs are added.
 */
export default function AccountPageHeader({
  title,
  description,
  badges,
  actions,
}: AccountPageHeaderProps) {
  return (
    <header className="flex min-h-24 flex-col gap-4 border-b border-slate-200 bg-white px-5 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950">
            {title}
          </h1>
          {badges && <div className="flex flex-wrap items-center gap-2">{badges}</div>}
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-600">
          {description}
        </p>
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-3">{actions}</div>
      )}
    </header>
  );
}
