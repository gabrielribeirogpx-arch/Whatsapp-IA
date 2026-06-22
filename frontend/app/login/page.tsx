'use client';

import { FormEvent, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  Bot,
  Check,
  Eye,
  LockKeyhole,
  Mail,
  Network,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import TurnstileWidget from '../../components/TurnstileWidget';
import { tenantLogin } from '../../lib/api';

const benefits = [
  { title: 'Segurança avançada', description: 'Proteção de dados com padrões modernos.', icon: ShieldCheck },
  { title: 'IA integrada', description: 'Automatize atendimentos e processos inteligentes.', icon: Bot },
  { title: 'Integrações oficiais', description: 'Google Workspace, MCP, APIs e muito mais.', icon: Network },
];

function GoogleIcon() {
  return (
    <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06L5.84 9.9C6.71 7.3 9.14 5.38 12 5.38z" />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(true);
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
      localStorage.setItem('remember_me', String(rememberMe));
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
    <main className="min-h-screen overflow-x-hidden bg-[#f7faf5] text-[#0e1c2a] antialiased lg:overflow-hidden">
      <div className="login-premium-layout relative grid min-h-screen lg:grid-cols-2">
        <div className="login-decor login-decor-left pointer-events-none absolute -left-24 top-1/3 hidden h-72 w-72 rounded-full bg-[#6CBF2A]/20 blur-3xl lg:block" />
        <div className="login-decor pointer-events-none absolute right-0 top-10 h-96 w-96 rounded-full bg-[#55B521]/15 blur-3xl" />
        <div className="login-decor pointer-events-none absolute bottom-0 right-0 h-80 w-80 rounded-full bg-[#6CBF2A]/10 blur-3xl" />

        <section className="login-premium-left relative hidden min-h-screen flex-col justify-center overflow-hidden bg-white px-10 py-8 lg:flex xl:px-16">
          <div className="absolute inset-y-0 right-0 w-1/2 opacity-40 [background-image:radial-gradient(circle_at_center,rgba(108,191,42,0.28)_1px,transparent_1px)] [background-size:28px_28px]" />
          <div className="absolute -right-24 top-16 h-[620px] w-[300px] rounded-[999px] border border-[#6CBF2A]/10 blur-[1px]" />
          <div className="absolute -right-10 top-0 h-full w-1/2 bg-[linear-gradient(110deg,transparent_0%,rgba(108,191,42,0.08)_100%)]" />

          <div className="relative z-10 animate-[fadeIn_700ms_ease-out_both]">
            <Image src="/Logo2.svg" alt="Wazza" width={210} height={48} priority className="login-brand-left h-auto w-40 xl:w-48" />
            <div className="login-hero-copy mt-10 max-w-xl">
              <div className="login-premium-pill mb-3 inline-flex items-center gap-2 rounded-full border border-[#6CBF2A]/20 bg-[#6CBF2A]/10 px-3.5 py-1.5 text-sm font-semibold text-[#2d7d12] shadow-sm">
                <Sparkles className="h-4 w-4" /> Plataforma SaaS premium
              </div>
              <h1 className="login-headline text-[3rem] font-black leading-[1.02] tracking-[-0.06em] text-[#0e1c2a] xl:text-[3.55rem]">
                Integre.<br />Automatize.<br />Escale <span className="text-[#55B521]">sem limites.</span>
              </h1>
              <p className="login-subtitle mt-5 max-w-lg text-base leading-7 text-slate-600">Acesse o poder do Wazza e conecte seus sistemas com segurança, inteligência e alta performance.</p>
            </div>
          </div>

          <div className="login-benefits relative z-10 mt-12 grid max-w-2xl grid-cols-3 gap-3">
            {benefits.map((benefit) => {
              const Icon = benefit.icon;
              return (
                <article key={benefit.title} className="login-benefit-card group rounded-[22px] border border-slate-200/80 bg-white/90 p-4 shadow-[0_16px_42px_rgba(15,23,42,0.07)] backdrop-blur transition duration-300 hover:-translate-y-1 hover:border-[#6CBF2A]/35 hover:shadow-[0_22px_60px_rgba(85,181,33,0.16)]">
                  <div className="login-benefit-icon mb-3 flex h-9 w-9 items-center justify-center rounded-2xl bg-gradient-to-br from-[#6CBF2A]/16 to-[#55B521]/8 text-[#389713] transition duration-300 group-hover:scale-105 group-hover:bg-[#6CBF2A]/15">
                    <Icon className="h-[18px] w-[18px]" />
                  </div>
                  <h2 className="text-sm font-bold text-[#0e1c2a]">{benefit.title}</h2>
                  <p className="login-benefit-desc mt-1 text-sm leading-5 text-slate-600">{benefit.description}</p>
                </article>
              );
            })}
          </div>
        </section>

        <section className="login-form-shell relative flex min-h-screen items-center justify-center px-4 py-4 sm:px-8 lg:px-10">
          <form className="login-premium-card w-full max-w-[540px] animate-[fadeInUp_650ms_ease-out_both] rounded-[30px] border border-white/80 bg-white p-6 shadow-[0_28px_90px_rgba(15,23,42,0.14)] backdrop-blur-xl sm:p-8 xl:p-10" onSubmit={onSubmit}>
            <div className="login-card-header text-center">
              <Image src="/Logo.svg" alt="Wazza" width={82} height={68} priority className="login-card-logo mx-auto h-[43px] w-[43px] object-contain drop-shadow-sm" />
              <h2 className="login-card-title mt-3 text-3xl font-black tracking-[-0.035em] text-[#0e1c2a] sm:text-[2rem]">Entrar no Wazza</h2>
              <p className="login-card-subtitle mt-3 text-sm leading-6 text-slate-500">Acesse seu workspace com email e senha.</p>
            </div>

            <div className="login-fields mt-6 space-y-4">
              <label className="block" htmlFor="email">
                <span className="mb-1.5 block text-sm font-semibold text-slate-700">Email</span>
                <span className="login-input-wrap group flex h-[52px] items-center gap-2.5 rounded-2xl border border-slate-200 bg-white px-4 shadow-sm transition duration-300 focus-within:border-[#6CBF2A] focus-within:shadow-[0_0_0_4px_rgba(108,191,42,0.14)]">
                  <Mail className="h-5 w-5 text-[#4a9f1c] transition group-focus-within:text-[#55B521]" />
                  <input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required placeholder="seu@email.com" className="h-full w-full border-0 bg-transparent text-base text-[#0e1c2a] outline-none placeholder:text-slate-400" />
                </span>
              </label>

              <label className="block" htmlFor="password">
                <span className="mb-1.5 block text-sm font-semibold text-slate-700">Senha</span>
                <span className="login-input-wrap group flex h-[52px] items-center gap-2.5 rounded-2xl border border-slate-200 bg-white px-4 shadow-sm transition duration-300 focus-within:border-[#6CBF2A] focus-within:shadow-[0_0_0_4px_rgba(108,191,42,0.14)]">
                  <LockKeyhole className="h-5 w-5 text-[#4a9f1c] transition group-focus-within:text-[#55B521]" />
                  <input id="password" type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required placeholder="••••••••" className="h-full w-full border-0 bg-transparent text-base text-[#0e1c2a] outline-none placeholder:text-slate-400" />
                  <Eye className="h-5 w-5 text-slate-400" aria-hidden="true" />
                </span>
              </label>
            </div>

            <div className="login-options mt-4 flex items-center justify-between gap-4 text-sm">
              <label className="inline-flex cursor-pointer items-center gap-2 font-medium text-slate-600">
                <input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} className="peer sr-only" />
                <span className="flex h-5 w-5 items-center justify-center rounded-md border border-slate-300 bg-white text-white shadow-sm transition peer-checked:border-[#55B521] peer-checked:bg-[#55B521]"><Check className="h-3.5 w-3.5" /></span>
                Lembrar de mim
              </label>
              <Link href="/forgot-password" className="font-semibold text-[#389713] transition hover:text-[#55B521] hover:underline hover:underline-offset-4">Esqueceu sua senha?</Link>
            </div>

            {error && <p className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{error}</p>}

            <div className="login-captcha mt-4 flex justify-center"><TurnstileWidget key={turnstileKey} action="login" token={turnstileToken} onToken={setTurnstileToken} onError={setError} /></div>

            <button type="submit" className="login-submit group mt-4 flex h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-[#55B521] to-[#43a114] px-4 text-base font-bold text-white shadow-[0_16px_34px_rgba(85,181,33,0.28)] transition duration-300 hover:-translate-y-0.5 hover:shadow-[0_22px_44px_rgba(85,181,33,0.34)] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60" disabled={isLoading || !turnstileToken}>
              {isLoading ? 'Entrando...' : 'Entrar'} <ArrowRight className="h-5 w-5 transition duration-300 group-hover:translate-x-1" />
            </button>

            <div className="login-divider my-4 flex items-center gap-4 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400"><span className="h-px flex-1 bg-slate-200" />OU<span className="h-px flex-1 bg-slate-200" /></div>

            <button type="button" className="login-google flex h-[52px] w-full items-center justify-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 text-base font-bold text-slate-700 shadow-sm transition duration-300 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg"><GoogleIcon />Continuar com Google</button>

            <div className="login-create mt-4 text-center">
              <p className="text-sm text-slate-500">Ainda não possui conta?</p>
              <Link href="/register" className="mt-3 flex h-[52px] w-full items-center justify-center gap-2 rounded-2xl border border-[#6CBF2A]/45 bg-white px-4 py-2 text-base font-bold text-[#389713] transition duration-300 hover:-translate-y-0.5 hover:border-[#55B521] hover:bg-[#6CBF2A]/5 hover:shadow-[0_16px_34px_rgba(85,181,33,0.14)]">Criar conta <ArrowRight className="h-5 w-5" /></Link>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
