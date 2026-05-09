'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { tenantLogin } from '../../lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      const tenant = await tenantLogin(email.trim(), password);
      localStorage.setItem('tenant', JSON.stringify(tenant));
      localStorage.setItem('token', tenant.token);
      localStorage.setItem('tenant_id', tenant.tenant_id);
      router.push('/chat');
    } catch {
      setError('Email ou senha inválidos.');
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
        <button type="submit" className="primary-button" disabled={isLoading}>{isLoading ? 'Entrando...' : 'Entrar'}</button>
        <p className="helper-text">Ainda não tem conta? <a href="/register">Criar conta</a></p>
      </form>
    </main>
  );
}
