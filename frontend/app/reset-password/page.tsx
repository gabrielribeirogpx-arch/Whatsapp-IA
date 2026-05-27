import { Suspense } from "react";

import ResetPasswordClient from "./ResetPasswordClient";

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="login-screen">
          <div className="login-card">
            <h1>Redefinir senha</h1>
            <p>Carregando recuperação segura...</p>
          </div>
        </main>
      }
    >
      <ResetPasswordClient />
    </Suspense>
  );
}
