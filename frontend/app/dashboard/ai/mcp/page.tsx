import { Suspense } from "react";
import MCPDashboardClient from "./MCPDashboardClient";

export default function MCPDashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-50 p-8 text-sm font-semibold text-slate-500">
          Carregando integrações...
        </div>
      }
    >
      <MCPDashboardClient />
    </Suspense>
  );
}
