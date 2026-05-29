"use client";

import { FormEvent, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";

import { resetPassword } from "../../lib/api";

export default function ResetPasswordClient() {
  const params = useSearchParams();
  const token = useMemo(() => params.get("token") || "", [params]);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const passwordRules = useMemo(() => ([
    ["Mínimo 8 caracteres", newPassword.length >= 8],
    ["Maiúscula", /[A-Z]/.test(newPassword)],
    ["Minúscula", /[a-z]/.test(newPassword)],
    ["Número", /\d/.test(newPassword)],
    ["Especial", /[^A-Za-z0-9]/.test(newPassword)]
  ] as const), [newPassword]);
  const strongPassword = passwordRules.every(([, ok]) => ok);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (!token) {
      setError("Token ausente.");
      return;
    }

    if (!strongPassword) {
      setError("A senha deve cumprir todos os requisitos de segurança.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("As senhas não coincidem.");
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, newPassword, confirmPassword);
      setSuccess("Senha atualizada com sucesso. Você já pode entrar.");
    } catch {
      setError("Token inválido ou expirado.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Redefinir senha</h1>
        <p>Defina sua nova senha com segurança.</p>
        <input
          type="password"
          minLength={8}
          required
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          placeholder="Nova senha"
        />
        <div className="grid gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs sm:grid-cols-2">
          {passwordRules.map(([label, ok]) => <span key={label} className={`inline-flex items-center gap-2 font-semibold ${ok ? "text-emerald-700" : "text-slate-500"}`}>{ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />} {label}</span>)}
        </div>
        <input
          type="password"
          minLength={8}
          required
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          placeholder="Confirmar senha"
        />
        {error && <p className="error-text">{error}</p>}
        {success && <p className="helper-text">{success}</p>}
        <button className="primary-button" disabled={loading}>
          {loading ? "Atualizando..." : "Atualizar senha"}
        </button>
      </form>
    </main>
  );
}
