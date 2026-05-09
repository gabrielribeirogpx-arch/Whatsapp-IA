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
      localStorage.setItem('token', tenant.token);
      localStorage.setItem('tenant_id', tenant.tenant_id);
      router.push('/chat');
      return;
    } catch (error) {
      if (error instanceof Error && error.message.includes('409')) {
        setNotice('Conta já existe. Fazendo login automático...');
        try {
          const tenant = await tenantLogin(phoneNumberId.trim());
          localStorage.setItem('tenant', JSON.stringify(tenant));
          localStorage.setItem('token', tenant.token);
          localStorage.setItem('tenant_id', tenant.tenant_id);
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
    <main className="onboarding-shell">
      <section className="onboarding-hero" aria-hidden="true">
        <div className="onboarding-glow" />
        <div className="onboarding-hero-content">
          <p className="onboarding-kicker">Plataforma SaaS de Conversas</p>
          <h1>
            Conecte conversas.
            <br />
            Potencialize negócios.
          </h1>
          <p className="onboarding-subtitle">
            Estruture atendimento, automação e inteligência em uma operação única para escalar com segurança.
          </p>

          <div className="onboarding-mockup">
            <div className="mockup-header">
              <span />
              <span />
              <span />
            </div>
            <div className="mockup-content">
              <div className="mockup-card" />
              <div className="mockup-card short" />
              <div className="mockup-chart" />
            </div>
          </div>

          <ul className="onboarding-badges">
            <li>✓ Multi-tenant</li>
            <li>✓ Fluxos automatizados</li>
            <li>✓ WhatsApp Oficial</li>
            <li>✓ IA integrada</li>
          </ul>
        </div>
      </section>

      <section className="onboarding-form-section">
        <form className="onboarding-card" onSubmit={onSubmit}>
          <div className="onboarding-step">
            <span>Boas-vindas</span>
            <strong>1 de 1</strong>
          </div>

          <h2>Crie sua conta</h2>
          <p className="onboarding-description">Leva menos de 1 minuto para ativar seu workspace.</p>

          <label htmlFor="name">Nome</label>
          <div className="input-wrap">
            <span>👤</span>
            <input id="name" value={name} onChange={(event) => setName(event.target.value)} required />
          </div>

          <label htmlFor="phone-number-id">ID Number</label>
          <div className="input-wrap">
            <span>🔐</span>
            <input
              id="phone-number-id"
              value={phoneNumberId}
              onChange={(event) => setPhoneNumberId(event.target.value)}
              required
            />
          </div>

          {notice && <p className="notice-text">{notice}</p>}
          {error && <p className="error-text">{error}</p>}

          <button type="submit" className="onboarding-cta" disabled={isLoading}>
            {isLoading ? 'Processando...' : 'Criar conta'}
          </button>

          <p className="helper-text onboarding-helper">
            Já tem conta? <a href="/login">Fazer login</a>
          </p>
        </form>
      </section>
    </main>
  );
}
