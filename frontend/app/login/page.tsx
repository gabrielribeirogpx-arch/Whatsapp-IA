'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { registerTenant, tenantLogin } from '../../lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const tenant = await registerTenant(name.trim(), phoneNumberId.trim());
      localStorage.setItem('tenant', JSON.stringify(tenant));
      router.push('/chat');
    } catch {
      try {
        const slug = name.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        const tenant = await tenantLogin(slug);
        localStorage.setItem('tenant', JSON.stringify(tenant));
        router.push('/chat');
      } catch {
        setError('Não foi possível criar ou autenticar o tenant. Verifique os dados e tente novamente.');
      }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Onboarding do tenant</h1>
        <p>Crie sua conta para começar a operar em modo multi-tenant.</p>

        <label htmlFor="name">Nome</label>
        <input id="name" value={name} onChange={(event) => setName(event.target.value)} required />

        <label htmlFor="phone-number-id">phone_number_id</label>
        <input
          id="phone-number-id"
          value={phoneNumberId}
          onChange={(event) => setPhoneNumberId(event.target.value)}
          required
        />

        {error && <p className="error-text">{error}</p>}

        <button type="submit" className="primary-button" disabled={isLoading}>
          {isLoading ? 'Processando...' : 'Criar conta'}
        </button>
      </form>
    </main>
  );
}
