"use client";
import { FormEvent, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { resetPassword } from "../../lib/api";

export default function ResetPasswordPage() {
  const params = useSearchParams();
  const token = useMemo(() => params.get("token") || "", [params]);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(""); setSuccess("");
    if (!token) return setError("Token ausente.");
    if (newPassword !== confirmPassword) return setError("As senhas não coincidem.");
    setLoading(true);
    try {
      await resetPassword(token, newPassword, confirmPassword);
      setSuccess("Senha atualizada com sucesso. Você já pode entrar.");
    } catch {
      setError("Token inválido ou expirado.");
    } finally { setLoading(false); }
  }

  return <main className="login-screen"><form className="login-card" onSubmit={onSubmit}><h1>Redefinir senha</h1><p>Defina sua nova senha com segurança.</p><input type="password" minLength={8} required value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="Nova senha" /><input type="password" minLength={8} required value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Confirmar senha" />{error && <p className="error-text">{error}</p>}{success && <p className="helper-text">{success}</p>}<button className="primary-button" disabled={loading}>{loading ? "Atualizando..." : "Atualizar senha"}</button></form></main>;
}
