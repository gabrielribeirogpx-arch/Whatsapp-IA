'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import { registerTenant, tenantLogin } from '../../lib/api';

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [phoneNumberId, setPhoneNumberId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setNotice('');
    setIsLoading(true);

    try {
      const tenant = await registerTenant(name.trim(), phoneNumberId.trim());
      localStorage.setItem('tenant', JSON.stringify(tenant));
      router.push('/chat');
      return;
    } catch (error) {
      if (error instanceof Error && error.message.includes('409')) {
        setNotice('Conta já existe. Fazendo login automático...');
        try {
          const tenant = await tenantLogin(phoneNumberId.trim());
          localStorage.setItem('tenant', JSON.stringify(tenant));
          router.push('/chat');
          return;
        } catch {
          setError('Conta existente encontrada, mas o login automático falhou.');
          return;
        }
      }

      setError('Não foi possível criar a conta. Verifique os dados e tente novamente.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="login-screen">
      <form className="login-card" onSubmit={onSubmit}>
        <h1>Cadastro do tenant</h1>
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

        {notice && <p className="notice-text">{notice}</p>}
        {error && <p className="error-text">{error}</p>}

        <button type="submit" className="primary-button" disabled={isLoading}>
          {isLoading ? 'Processando...' : 'Criar conta'}
        </button>

        <p className="helper-text">
          Já tem conta? <a href="/login">Fazer login</a>
        </p>
      </form>
    </main>
  );
}
