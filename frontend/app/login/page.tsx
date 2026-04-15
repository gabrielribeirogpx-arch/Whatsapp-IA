'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { tenantLogin } from '../../lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const tenant = await tenantLogin(phoneNumberId.trim());
      localStorage.setItem('tenant', JSON.stringify(tenant));
      localStorage.setItem('tenant_id', tenant.tenant_id);
      router.push('/chat');
    } catch {
      setError('Não foi possível autenticar o tenant. Verifique os dados e tente novamente.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Login do tenant</h1>
        <p>Entre com seu phone_number_id para acessar o sistema.</p>

        <label htmlFor="phone-number-id">phone_number_id</label>
        <input
          id="phone-number-id"
          value={phoneNumberId}
          onChange={(event) => setPhoneNumberId(event.target.value)}
          required
        />

        {error && <p className="error-text">{error}</p>}

        <button type="submit" className="primary-button" disabled={isLoading}>
          {isLoading ? 'Entrando...' : 'Entrar'}
        </button>

        <p className="helper-text">
          Ainda não tem conta? <a href="/register">Criar conta</a>
        </p>
      </form>
    </main>
  );
}
