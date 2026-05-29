"use client";
import { FormEvent, useState } from "react";
import TurnstileWidget from "../../components/TurnstileWidget";
import { forgotPassword } from "../../lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");
  const [turnstileKey, setTurnstileKey] = useState(0);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setError("");
    if (!turnstileToken) {
      setError("Conclua a validação de segurança para continuar.");
      return;
    }

    setLoading(true);
    try {
      await forgotPassword(email.trim(), turnstileToken);
      setMessage("Se o email existir, enviaremos as instruções de recuperação.");
    } catch {
      setTurnstileToken("");
      setTurnstileKey((value) => value + 1);
      setError("Não foi possível validar a solicitação. Tente novamente.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="login-screen"><form className="login-card" onSubmit={onSubmit}><h1>Recuperar senha</h1><p>Informe seu e-mail para receber o link seguro.</p><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /><TurnstileWidget key={turnstileKey} action="forgot-password" token={turnstileToken} onToken={setTurnstileToken} onError={setError} /><button type="submit" className="primary-button" disabled={loading || !turnstileToken}>{loading ? "Enviando..." : "Enviar link"}</button>{error && <p className="error-text">{error}</p>}{message && <p className="helper-text">{message}</p>}</form></main>;
}
