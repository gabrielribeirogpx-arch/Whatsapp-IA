'use client';

/**
 * MobileLoginScreen.tsx — Wazza Inbox Mobile
 * Tela de login mobile com identidade Wazza + Cloudflare Turnstile.
 * Reutiliza: TurnstileWidget, tenantLogin (lib/api), mesmo endpoint do desktop.
 */

import { FormEvent, useState } from 'react';
import { Eye, EyeOff, Lock, Mail } from 'lucide-react';
import TurnstileWidget from '@/components/TurnstileWidget';
import { tenantLogin } from '@/lib/api';

interface MobileLoginScreenProps {
  onSuccess: () => void;
}

export default function MobileLoginScreen({ onSuccess }: MobileLoginScreenProps) {
  const [email, setEmail]                 = useState('');
  const [password, setPassword]           = useState('');
  const [showPass, setShowPass]           = useState(false);
  const [error, setError]                 = useState('');
  const [isLoading, setIsLoading]         = useState(false);
  const [turnstileToken, setTurnstileToken] = useState('');
  const [turnstileKey, setTurnstileKey]   = useState(0);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
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
      onSuccess();
    } catch {
      setTurnstileToken('');
      setTurnstileKey((v) => v + 1);
      setError('Email, senha ou validação de segurança inválidos.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: '100dvh',
      background: '#FFFFFF',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px 20px calc(env(safe-area-inset-bottom,0px) + 24px)',
      fontFamily: "'DM Sans', sans-serif",
    }}>
      {/* Logo */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          marginBottom: '40px',
        }}
      >
      <img
        src="/Logo.svg"
        alt="Wazza"
        style={{
          width: '180px',
          height: 'auto',
          objectFit: 'contain',
        }}
     />
  </div>

      {/* Card */}
      <div style={{
        width: '100%', maxWidth: '380px',
        background: '#FFFFFF',
        border: '1px solid #E5E7EB',
        borderRadius: '20px',
        padding: '28px 24px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
      }}>
        <h2 style={{
          margin: '0 0 20px', fontSize: '18px', fontWeight: 600, color: '#111827',
        }}>
          Entrar
        </h2>

        <form onSubmit={onSubmit}>
          {/* Email */}
          <div style={{ marginBottom: '14px' }}>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, color: '#374151', marginBottom: '6px' }}>
              Email
            </label>
            <div style={{ position: 'relative' }}>
              <Mail size={16} style={{
                position: 'absolute', left: '12px', top: '50%',
                transform: 'translateY(-50%)', color: '#9CA3AF', pointerEvents: 'none',
              }} />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="seu@email.com"
                required
                autoComplete="email"
                style={{
                  width: '100%', height: '44px',
                  background: '#F9FAFB', border: '1px solid #E5E7EB',
                  borderRadius: '10px', paddingLeft: '38px', paddingRight: '12px',
                  fontSize: '14px', color: '#111827', outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {/* Senha */}
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, color: '#374151', marginBottom: '6px' }}>
              Senha
            </label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{
                position: 'absolute', left: '12px', top: '50%',
                transform: 'translateY(-50%)', color: '#9CA3AF', pointerEvents: 'none',
              }} />
              <input
                type={showPass ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Mínimo 8 caracteres"
                minLength={8}
                required
                autoComplete="current-password"
                style={{
                  width: '100%', height: '44px',
                  background: '#F9FAFB', border: '1px solid #E5E7EB',
                  borderRadius: '10px', paddingLeft: '38px', paddingRight: '44px',
                  fontSize: '14px', color: '#111827', outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
              <button
                type="button"
                onClick={() => setShowPass((v) => !v)}
                style={{
                  position: 'absolute', right: '12px', top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'transparent', border: 'none',
                  cursor: 'pointer', color: '#9CA3AF', padding: '2px',
                  WebkitTapHighlightColor: 'transparent',
                }}
              >
                {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Erro */}
          {error && (
            <div style={{
              background: 'rgba(226,75,74,0.08)',
              border: '1px solid rgba(226,75,74,0.2)',
              borderRadius: '8px', padding: '10px 12px',
              marginBottom: '16px',
              fontSize: '13px', color: '#e24b4a',
            }}>
              {error}
            </div>
          )}

          {/* Turnstile — reutiliza exatamente o mesmo componente do login desktop */}
          <div style={{ marginBottom: '20px' }}>
            <TurnstileWidget
              key={turnstileKey}
              action="login"
              token={turnstileToken}
              onToken={setTurnstileToken}
              onError={setError}
            />
          </div>

          {/* Botão */}
          <button
            type="submit"
            disabled={isLoading || !turnstileToken}
            style={{
              width: '100%', height: '48px',
              background: isLoading || !turnstileToken ? '#D1FAE5' : '#59C414',
              border: 'none', borderRadius: '12px',
              fontSize: '15px', fontWeight: 600,
              color: isLoading || !turnstileToken ? '#6B7280' : '#fff',
              cursor: isLoading || !turnstileToken ? 'default' : 'pointer',
              transition: 'background 0.2s',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            {isLoading ? 'Entrando…' : 'Entrar'}
          </button>
        </form>

        {/* Links */}
        <div style={{ marginTop: '20px', textAlign: 'center' }}>
          <a href="/forgot-password" style={{ fontSize: '13px', color: '#59C414', textDecoration: 'none' }}>
            Esqueceu sua senha?
          </a>
        </div>
      </div>

      {/* Footer */}
      <p style={{ marginTop: '32px', fontSize: '12px', color: '#9CA3AF', textAlign: 'center' }}>
        © {new Date().getFullYear()} Wazza · Powered by WhatsApp Business
      </p>
    </div>
  );
}
