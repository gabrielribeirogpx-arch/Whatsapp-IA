"use client";
import { FormEvent, useState } from "react";
import { forgotPassword } from "../../lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      await forgotPassword(email.trim());
      setMessage("Se o email existir, enviaremos as instruções de recuperação.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="login-screen"><form className="login-card" onSubmit={onSubmit}><h1>Recuperar senha</h1><p>Informe seu e-mail para receber o link seguro.</p><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /><button type="submit" className="primary-button" disabled={loading}>{loading ? "Enviando..." : "Enviar link"}</button>{message && <p className="helper-text">{message}</p>}</form></main>;
}
