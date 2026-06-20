import { Suspense } from "react";
import MCPDashboardClient from "./MCPDashboardClient";

function MCPDashboardFallback() {
  return (
    <main className="min-h-screen w-full min-w-0 bg-slate-50 px-5 py-6 text-slate-900 lg:px-8">
      <div className="w-full min-w-0 space-y-6">
        <div className="rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-200/60">
          <p className="text-sm font-semibold text-slate-500">
            Carregando integrações de IA...
          </p>
        </div>
      </div>
    </main>
  );
}

export default function MCPDashboardPage() {
  return (
    <Suspense fallback={<MCPDashboardFallback />}>
      <MCPDashboardClient />
    </Suspense>
  );
}
