'use client';

import { FormEvent, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { registerTenant } from '../../lib/api';

export default function RegisterPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ full_name:'', email:'', password:'', confirm_password:'', business_name:'', whatsapp_number:'', business_segment:'', intended_use:'', team_size:'', monthly_message_volume:'' });

  const passwordOk = useMemo(() => form.password.length >= 8 && form.password === form.confirm_password, [form]);
  const next = () => setStep((s) => Math.min(4, s + 1));
  const prev = () => setStep((s) => Math.max(1, s - 1));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!passwordOk) return setError('Senha mínima de 8 caracteres e confirmação idêntica.');
    setIsLoading(true); setError('');
    try {
      const tenant = await registerTenant(form);
      localStorage.setItem('tenant', JSON.stringify(tenant));
      localStorage.setItem('token', tenant.token);
      localStorage.setItem('tenant_id', tenant.tenant_id);
      router.push('/chat');
    } catch (e) {
      setError(e instanceof Error && e.message.includes('409') ? 'Email já cadastrado.' : 'Falha ao criar conta.');
    } finally { setIsLoading(false); }
  }

  return <main className="onboarding-shell"><section className="onboarding-hero" aria-hidden="true"><div className="onboarding-glow" /><div className="onboarding-hero-content"><p className="onboarding-kicker">Wazza API</p><h1>Atendimento WhatsApp em padrão SaaS.</h1><p className="onboarding-subtitle">Onboarding profissional para escalar seu time com automação, CRM e IA.</p></div></section><section className="onboarding-form-section"><form className="onboarding-card" onSubmit={submit}><div className="onboarding-step"><span>Etapa {step}</span><strong>{step} de 4</strong></div><h2>Crie sua conta</h2>
  {step===1 && <><label>Nome completo</label><input value={form.full_name} onChange={e=>setForm({...form, full_name:e.target.value})} required /><label>Email</label><input type="email" value={form.email} onChange={e=>setForm({...form, email:e.target.value})} required /><label>Senha</label><input type="password" minLength={8} value={form.password} onChange={e=>setForm({...form, password:e.target.value})} required /><label>Confirmar senha</label><input type="password" minLength={8} value={form.confirm_password} onChange={e=>setForm({...form, confirm_password:e.target.value})} required /></>}
  {step===2 && <><label>Nome do negócio</label><input value={form.business_name} onChange={e=>setForm({...form, business_name:e.target.value})} required /><label>Segmento</label><input value={form.business_segment} onChange={e=>setForm({...form, business_segment:e.target.value})} required /><label>Tamanho do time (opcional)</label><input value={form.team_size} onChange={e=>setForm({...form, team_size:e.target.value})} /></>}
  {step===3 && <><label>Número WhatsApp</label><input value={form.whatsapp_number} onChange={e=>setForm({...form, whatsapp_number:e.target.value})} required /><label>Volume mensal (opcional)</label><input value={form.monthly_message_volume} onChange={e=>setForm({...form, monthly_message_volume:e.target.value})} /><label>Uso pretendido</label><input value={form.intended_use} onChange={e=>setForm({...form, intended_use:e.target.value})} required /></>}
  {step===4 && <p className="onboarding-description">Revise os dados e finalize a criação do seu workspace.</p>}
  {error && <p className="error-text">{error}</p>}
  <div style={{display:'flex', gap:12}}>{step>1 && <button type="button" className="onboarding-cta" onClick={prev}>Voltar</button>}{step<4 ? <button type="button" className="onboarding-cta" onClick={next}>Continuar</button> : <button type="submit" className="onboarding-cta" disabled={isLoading}>{isLoading ? 'Processando...' : 'Finalizar'}</button>}</div>
</form></section></main>;
}
