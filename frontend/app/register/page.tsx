'use client';

import { FormEvent, useMemo, useState } from 'react';
import Image from 'next/image';
import { ArrowRight, CheckCircle2, LockKeyhole, MessageCircle, ShieldCheck, Sparkles } from 'lucide-react';
import { useRouter } from 'next/navigation';
import TurnstileWidget from '../../components/TurnstileWidget';
import { registerTenant } from '../../lib/api';

type RegisterForm = {
  full_name: string;
  email: string;
  password: string;
  confirm_password: string;
  business_name: string;
  whatsapp_number: string;
  business_segment: string;
  intended_use: string;
  team_size: string;
  monthly_message_volume: string;
};

const INITIAL_FORM: RegisterForm = {
  full_name: '',
  email: '',
  password: '',
  confirm_password: '',
  business_name: '',
  whatsapp_number: '',
  business_segment: '',
  intended_use: '',
  team_size: '',
  monthly_message_volume: ''
};

export default function RegisterPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof RegisterForm, string>>>({});
  const [form, setForm] = useState<RegisterForm>(INITIAL_FORM);
  const [turnstileToken, setTurnstileToken] = useState('');
  const [turnstileKey, setTurnstileKey] = useState(0);

  const passwordRules = useMemo(() => ([
    ['Mínimo 8 caracteres', form.password.length >= 8],
    ['Maiúscula', /[A-Z]/.test(form.password)],
    ['Minúscula', /[a-z]/.test(form.password)],
    ['Número', /\d/.test(form.password)],
    ['Especial', /[^A-Za-z0-9]/.test(form.password)]
  ] as const), [form.password]);
  const strongPassword = passwordRules.every(([, ok]) => ok);
  const passwordOk = useMemo(() => strongPassword && form.password === form.confirm_password, [strongPassword, form.password, form.confirm_password]);

  const updateField = (field: keyof RegisterForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    setFieldErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const validateStep = (targetStep: number): boolean => {
    const nextErrors: Partial<Record<keyof RegisterForm, string>> = {};

    if (targetStep >= 1) {
      if (!form.full_name.trim()) nextErrors.full_name = 'Informe seu nome completo.';
      if (!form.email.trim()) nextErrors.email = 'Informe um email válido.';
      if (!form.password.trim()) nextErrors.password = 'Informe uma senha.';
      if (!form.confirm_password.trim()) nextErrors.confirm_password = 'Confirme sua senha.';
      if (!passwordOk) nextErrors.confirm_password = 'A senha deve cumprir a política forte e a confirmação precisa ser idêntica.';
    }

    if (targetStep >= 2) {
      if (!form.business_name.trim()) nextErrors.business_name = 'Informe o nome do negócio.';
      if (!form.business_segment.trim()) nextErrors.business_segment = 'Informe o segmento.';
    }

    if (targetStep >= 3) {
      if (!form.whatsapp_number.trim()) nextErrors.whatsapp_number = 'Informe o número do WhatsApp.';
      if (form.intended_use.trim().length < 2) nextErrors.intended_use = 'Descreva o uso pretendido com pelo menos 2 caracteres.';
    }

    setFieldErrors((prev) => ({ ...prev, ...nextErrors }));
    return Object.keys(nextErrors).length === 0;
  };

  const next = () => {
    if (!validateStep(step)) {
      setError('Preencha os campos obrigatórios antes de continuar.');
      return;
    }
    console.log('[ONBOARDING STEP DATA]', { step, data: { ...form, password: '***', confirm_password: '***' } });
    setError('');
    setStep((s) => Math.min(4, s + 1));
  };

  const prev = () => setStep((s) => Math.max(1, s - 1));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!validateStep(3)) {
      setError('Existem campos inválidos. Revise os destaques em vermelho.');
      return;
    }

    if (!turnstileToken) {
      setError('Conclua a validação de segurança para finalizar o onboarding.');
      return;
    }

    const payload: RegisterForm = {
      ...form,
      full_name: form.full_name.trim(),
      email: form.email.trim(),
      business_name: form.business_name.trim(),
      whatsapp_number: form.whatsapp_number.trim(),
      business_segment: form.business_segment.trim(),
      intended_use: form.intended_use.trim(),
      team_size: form.team_size.trim(),
      monthly_message_volume: form.monthly_message_volume.trim()
    };

    setIsLoading(true);
    setError('');
    console.log('[ONBOARDING FINAL PAYLOAD]', { ...payload, password: '***', confirm_password: '***' });
    try {
      const tenant = await registerTenant(payload, turnstileToken);
      localStorage.setItem('tenant', JSON.stringify(tenant));
      localStorage.setItem('token', tenant.token);
      localStorage.setItem('tenant_id', tenant.tenant_id);
      router.replace('/dashboard?welcome=1');
    } catch (e) {
      const message = e instanceof Error ? e.message : '';
      setTurnstileToken('');
      setTurnstileKey((value) => value + 1);
      if (message.includes('409')) {
        setError('Não foi possível criar a conta com estes dados.');
      } else if (message.includes('intended_use')) {
        setFieldErrors((prev) => ({ ...prev, intended_use: 'Uso pretendido é obrigatório e deve ter ao menos 2 caracteres.' }));
        setStep(3);
        setError('Campo "Uso pretendido" inválido. Preencha com pelo menos 2 caracteres.');
      } else {
        setError('Não foi possível criar a conta. Revise os campos obrigatórios e tente novamente.');
      }
    } finally {
      setIsLoading(false);
    }
  }

  const hasError = (field: keyof RegisterForm) => Boolean(fieldErrors[field]);

  const progressPercent = (step / 4) * 100;
  const stepTitles: Record<number, string> = {
    1: 'Crie seu acesso seguro',
    2: 'Conte sobre seu negócio',
    3: 'Configure o canal principal',
    4: 'Finalize seu workspace'
  };
  const stepDescriptions: Record<number, string> = {
    1: 'Use um email profissional e uma senha forte para proteger seu workspace Wazza API.',
    2: 'Essas informações ajudam a personalizar sua operação e experiência inicial.',
    3: 'Informe o WhatsApp e o volume esperado para preparar sua automação.',
    4: 'Revise os dados e conclua a validação de segurança para entrar no Wazza API.'
  };

  return (
    <main className="onboarding-shell">
      <div className="onboarding-decor onboarding-decor-left" />
      <div className="onboarding-decor onboarding-decor-right" />

      <section className="onboarding-hero" aria-label="Apresentação Wazza API">
        <div className="onboarding-glow" />
        <div className="onboarding-hero-content">
          <Image src="/Logo2.svg" alt="Wazza API" width={210} height={48} priority className="onboarding-brand" />
          <div className="onboarding-copy">
            <p className="onboarding-kicker"><Sparkles size={15} /> Onboarding premium</p>
            <h1>Comece sua operação inteligente no Wazza API.</h1>
            <p className="onboarding-subtitle">Configure seu workspace com uma experiência segura, guiada e pronta para escalar atendimento, CRM e automações no WhatsApp.</p>
          </div>
          <div className="onboarding-mockup" aria-hidden="true">
            <div className="mockup-header"><span /><span /><span /></div>
            <div className="mockup-content">
              <div className="mockup-card" />
              <div className="mockup-card short" />
              <div className="mockup-chart" />
            </div>
          </div>
          <ul className="onboarding-badges" aria-label="Benefícios do Wazza API">
            <li><ShieldCheck size={18} /> Segurança com validação</li>
            <li><MessageCircle size={18} /> WhatsApp + CRM</li>
            <li><LockKeyhole size={18} /> Senha forte</li>
            <li><Sparkles size={18} /> IA para escalar</li>
          </ul>
        </div>
      </section>

      <section className="onboarding-form-section">
        <form className="onboarding-card" onSubmit={submit}>
          <div className="onboarding-card-header">
            <Image src="/Logo.svg" alt="Wazza API" width={82} height={68} priority className="onboarding-card-logo" />
            <div className="onboarding-step">
              <span>Etapa {step}</span>
              <strong>{step} de 4</strong>
            </div>
            <div className="onboarding-progress" aria-hidden="true"><span style={{ width: `${progressPercent}%` }} /></div>
            <h2>{stepTitles[step]}</h2>
            <p className="onboarding-description">{stepDescriptions[step]}</p>
          </div>

          <div className="onboarding-fields">
            {step===1 && <><label className="onboarding-label">Nome completo</label><input className={`onboarding-input ${hasError('full_name') ? 'onboarding-input--error' : ''}`} placeholder="Seu nome completo" value={form.full_name} onChange={e=>updateField('full_name', e.target.value)} required />{fieldErrors.full_name && <p className="error-text">{fieldErrors.full_name}</p>}<label className="onboarding-label">Email</label><input className={`onboarding-input ${hasError('email') ? 'onboarding-input--error' : ''}`} placeholder="voce@empresa.com" type="email" value={form.email} onChange={e=>updateField('email', e.target.value)} required />{fieldErrors.email && <p className="error-text">{fieldErrors.email}</p>}<label className="onboarding-label">Senha</label><input className={`onboarding-input ${hasError('password') ? 'onboarding-input--error' : ''}`} placeholder="Crie uma senha forte" type="password" minLength={8} value={form.password} onChange={e=>updateField('password', e.target.value)} required /><div className="onboarding-password-rules">{passwordRules.map(([label, ok]) => <span key={label} className={ok ? 'is-valid' : ''}>{ok ? <CheckCircle2 size={15} /> : <span className="rule-dot" />} {label}</span>)}</div><label className="onboarding-label">Confirmar senha</label><input className={`onboarding-input ${hasError('confirm_password') ? 'onboarding-input--error' : ''}`} placeholder="Repita sua senha" type="password" minLength={8} value={form.confirm_password} onChange={e=>updateField('confirm_password', e.target.value)} required />{fieldErrors.confirm_password && <p className="error-text">{fieldErrors.confirm_password}</p>}</>}
            {step===2 && <><label className="onboarding-label">Nome do negócio</label><input className={`onboarding-input ${hasError('business_name') ? 'onboarding-input--error' : ''}`} placeholder="Nome da sua empresa" value={form.business_name} onChange={e=>updateField('business_name', e.target.value)} required />{fieldErrors.business_name && <p className="error-text">{fieldErrors.business_name}</p>}<label className="onboarding-label">Segmento</label><input className={`onboarding-input ${hasError('business_segment') ? 'onboarding-input--error' : ''}`} placeholder="Ex.: Clínica, imobiliária, ecommerce" value={form.business_segment} onChange={e=>updateField('business_segment', e.target.value)} required />{fieldErrors.business_segment && <p className="error-text">{fieldErrors.business_segment}</p>}<label className="onboarding-label">Tamanho do time (opcional)</label><input className="onboarding-input" placeholder="Ex.: 2-5 pessoas" value={form.team_size} onChange={e=>updateField('team_size', e.target.value)} /></>}
            {step===3 && <><label className="onboarding-label">Número WhatsApp</label><input className={`onboarding-input ${hasError('whatsapp_number') ? 'onboarding-input--error' : ''}`} placeholder="Ex.: +55 11 99999-9999" value={form.whatsapp_number} onChange={e=>updateField('whatsapp_number', e.target.value)} required />{fieldErrors.whatsapp_number && <p className="error-text">{fieldErrors.whatsapp_number}</p>}<label className="onboarding-label">Volume mensal (opcional)</label><input className="onboarding-input" placeholder="Ex.: 1.000 mensagens/mês" value={form.monthly_message_volume} onChange={e=>updateField('monthly_message_volume', e.target.value)} /><label className="onboarding-label">Uso pretendido</label><input className={`onboarding-input ${hasError('intended_use') ? 'onboarding-input--error' : ''}`} placeholder="Ex.: Atendimento, vendas e pós-venda" value={form.intended_use} onChange={e=>updateField('intended_use', e.target.value)} required />{fieldErrors.intended_use && <p className="error-text">{fieldErrors.intended_use}</p>}</>}
            {step===4 && <><div className="onboarding-review-card"><CheckCircle2 size={18} /><div><strong>Quase lá</strong><p>Valide a segurança e finalize a criação do workspace Wazza API.</p></div></div><TurnstileWidget key={turnstileKey} action="register" token={turnstileToken} onToken={setTurnstileToken} onError={setError} /></>}
          </div>

          {error && <p className="error-text">{error}</p>}
          <div className="onboarding-actions">{step>1 && <button type="button" className="onboarding-cta onboarding-cta--secondary" onClick={prev}>Voltar</button>}{step<4 ? <button type="button" className="onboarding-cta" onClick={next}>Continuar <ArrowRight size={18} /></button> : <button type="submit" className="onboarding-cta" disabled={isLoading || !turnstileToken}>{isLoading ? 'Processando...' : 'Finalizar'}</button>}</div>
        </form>
      </section>
    </main>
  );
}
