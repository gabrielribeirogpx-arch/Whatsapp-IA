'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import TurnstileWidget from '../../components/TurnstileWidget';
import { tenantLogin } from '../../lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState('');
  const [turnstileKey, setTurnstileKey] = useState(0);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    if (!turnstileToken) {
      setError('Conclua a validação de segurança para continuar.');
      return;
    }

    setIsLoading(true);
    try {
      const tenant = await tenantLogin(email.trim(), password, turnstileToken);
      localStorage.setItem('tenant', JSON.stringify(tenant));
      localStorage.setItem('token', tenant.token);
      localStorage.setItem('tenant_id', tenant.tenant_id);
      router.replace('/dashboard');
    } catch {
      setTurnstileToken('');
      setTurnstileKey((value) => value + 1);
      setError('Email, senha ou validação de segurança inválidos.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Entrar na Wazza API</h1>
        <p>Acesse seu workspace com email e senha.</p>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <label htmlFor="password">Senha</label>
        <input id="password" type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required />
        {error && <p className="error-text">{error}</p>}
        <TurnstileWidget key={turnstileKey} action="login" token={turnstileToken} onToken={setTurnstileToken} onError={setError} />
        <button type="submit" className="primary-button" disabled={isLoading || !turnstileToken}>{isLoading ? 'Entrando...' : 'Entrar'}</button>
        <p className="helper-text"><a href="/forgot-password">Esqueceu sua senha?</a></p>
        <p className="helper-text">Ainda não tem conta? <a href="/register">Criar conta</a></p>
      </form>
    </main>
  );
}
