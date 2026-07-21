'use client';

import Link from 'next/link';
import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Check, ChevronLeft, ChevronRight, HelpCircle, Sparkles, X } from 'lucide-react';
import { listFlows, listWhatsAppProviders } from '@/lib/api';
import { getMissionRoute, OnboardingMissionId } from '@/lib/onboarding/missionRoutes';

export type OnboardingStep = { id: OnboardingMissionId; title: string; description: string; action: string };
export type MissionStatus = 'pending' | 'active' | 'completed';
export type TutorialState = {
  /** The assistant card being displayed. This is deliberately independent from completion. */
  currentStep: number;
  missionStatus: Record<string, MissionStatus>;
  completed: string[];
  dismissedScreens: string[];
  tourDismissed: boolean;
};
const STORAGE_KEY = 'wazza:onboarding:tenant:default';
export const onboardingSteps: OnboardingStep[] = [
  { id: 'company', title: 'Criar empresa', description: 'Defina a operação que será atendida.', action: 'Abrir configurações' },
  { id: 'whatsapp', title: 'Conectar WhatsApp', description: 'Conecte seu canal para receber mensagens reais.', action: 'Conectar agora' },
  { id: 'flow', title: 'Criar primeiro fluxo', description: 'Monte a automação que orienta cada conversa.', action: 'Criar fluxo' },
  { id: 'message', title: 'Receber primeira mensagem', description: 'Use a demonstração ou seu WhatsApp conectado.', action: 'Abrir Inbox' },
  { id: 'inbox', title: 'Testar Inbox', description: 'Veja, responda e encaminhe uma conversa.', action: 'Testar Inbox' },
  { id: 'pipeline', title: 'Criar Pipeline', description: 'Organize oportunidades em etapas comerciais.', action: 'Abrir Pipeline' },
  { id: 'ai', title: 'Configurar IA', description: 'Defina como a IA ajuda sua equipe.', action: 'Configurar IA' },
  { id: 'publish', title: 'Publicar automação', description: 'Ative o fluxo para colocá-lo em operação.', action: 'Publicar fluxo' },
  { id: 'team', title: 'Convidar equipe', description: 'Traga operadores para atender juntos.', action: 'Convidar equipe' },
];
const screenHelp: Record<string, { title: string; text: string; bullets: string[] }> = {
  '/dashboard': { title: 'Dashboard', text: 'Visão geral da sua operação.', bullets: ['Acompanhe conversas e resultados', 'Encontre próximos passos sugeridos'] },
  '/dashboard/inbox': { title: 'Inbox', text: 'Aqui chegam todas as mensagens dos seus clientes.', bullets: ['Responda manualmente ou com IA', 'Transfira para operadores e consulte o CRM'] },
  '/dashboard/clients': { title: 'CRM', text: 'Armazena informações e o histórico de cada cliente.', bullets: ['Registre tags e observações', 'Use dados para personalizar o atendimento'] },
  '/dashboard/pipeline': { title: 'Pipeline', text: 'Organiza oportunidades até a venda.', bullets: ['Arraste leads entre etapas', 'Descubra onde sua operação perde oportunidades'] },
  '/dashboard/flows': { title: 'Fluxos', text: 'Automatiza processos e respostas.', bullets: ['Combine mensagens, condições e IA', 'Publique quando estiver pronto'] },
  '/dashboard/observability': { title: 'Observabilidade', text: 'Mostra tudo que aconteceu em cada execução.', bullets: ['Siga mensagens, fluxo, IA e resposta', 'Use traces para investigar e melhorar'] },
};
type ContextValue = {
  state: TutorialState;
  complete: (id: string) => void;
  activate: (id: string) => void;
  reset: () => void;
  progress: number;
  startTour: () => void;
};
const OnboardingContext = createContext<ContextValue | null>(null);
export const useOnboarding = () => { const value = useContext(OnboardingContext); if (!value) throw new Error('useOnboarding must be used inside OnboardingProvider'); return value; };

const initialState: TutorialState = { currentStep: 0, missionStatus: {}, completed: [], dismissedScreens: [], tourDismissed: false };

function statusFor(state: TutorialState, id: string): MissionStatus {
  return state.missionStatus[id] || (state.completed.includes(id) ? 'completed' : 'pending');
}

function readState(): TutorialState {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Partial<TutorialState>;
    const completed = Array.isArray(stored.completed) ? stored.completed : [];
    const missionStatus = { ...(stored.missionStatus || {}) };
    completed.forEach((id) => { missionStatus[id] = 'completed'; });
    const migratedCurrentStep = onboardingSteps.findIndex((step) => !completed.includes(step.id));
    const currentStep = typeof stored.currentStep === 'number'
      ? stored.currentStep
      : (migratedCurrentStep === -1 ? onboardingSteps.length - 1 : migratedCurrentStep);
    return {
      ...initialState,
      ...stored,
      completed,
      missionStatus,
      currentStep: Math.min(Math.max(currentStep, 0), onboardingSteps.length - 1),
    };
  } catch {
    return initialState;
  }
}
export function OnboardingProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [state, setState] = useState<TutorialState>(initialState);
  const [ready, setReady] = useState(false); const [helpOpen, setHelpOpen] = useState(false); const [tourOpen, setTourOpen] = useState(false); const [tourIndex, setTourIndex] = useState(0);
  const complete = useCallback((id: string) => setState(old => {
    const stepIndex = onboardingSteps.findIndex((step) => step.id === id);
    return {
      ...old,
      completed: old.completed.includes(id) ? old.completed : [...old.completed, id],
      missionStatus: { ...old.missionStatus, [id]: 'completed' },
      currentStep: stepIndex === old.currentStep ? Math.min(stepIndex + 1, onboardingSteps.length - 1) : old.currentStep,
    };
  }), []);
  const activate = useCallback((id: string) => setState(old => {
    const stepIndex = onboardingSteps.findIndex((step) => step.id === id);
    return {
      ...old,
      missionStatus: { ...old.missionStatus, [id]: statusFor(old, id) === 'completed' ? 'completed' : 'active' },
      // Navigating is progress through the assistant, not evidence that the mission succeeded.
      currentStep: stepIndex >= 0 ? Math.min(stepIndex + 1, onboardingSteps.length - 1) : old.currentStep,
    };
  }), []);
  useEffect(() => { setState(readState()); setReady(true); }, []);
  useEffect(() => { if (ready) localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }, [state, ready]);
  useEffect(() => {
    if (!ready || state.completed.includes('publish')) return;

    let cancelled = false;
    const checkPublishedFlow = async () => {
      try {
        const flows = await listFlows();
        if (!cancelled && flows.some((flow) => flow.published || flow.is_published || flow.status === 'published')) complete('publish');
      } catch {
        // The mission remains pending when flows cannot be loaded.
      }
    };

    void checkPublishedFlow();
    const interval = window.setInterval(() => { void checkPublishedFlow(); }, 30_000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [complete, ready, state.completed]);
  useEffect(() => {
    if (!ready || statusFor(state, 'whatsapp') === 'completed') return;

    let cancelled = false;
    const checkWhatsAppConnection = async () => {
      try {
        const providers = await listWhatsAppProviders();
        const hasActiveConnection = providers.some((provider) =>
          provider.is_active ||
          provider.connection_status === 'connected' ||
          provider.status === 'connected' ||
          provider.status === 'active',
        );
        if (!cancelled && hasActiveConnection) complete('whatsapp');
      } catch {
        // Keep the mission active/pending until the provider status can be verified.
      }
    };

    void checkWhatsAppConnection();
    const interval = window.setInterval(() => { void checkWhatsAppConnection(); }, 30_000);
    window.addEventListener('wazza:whatsapp-connection-changed', checkWhatsAppConnection);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('wazza:whatsapp-connection-changed', checkWhatsAppConnection);
    };
  }, [complete, ready, state]);
  useEffect(() => { setHelpOpen(Boolean(ready && screenHelp[pathname] && !state.dismissedScreens.includes(pathname))); }, [pathname, ready, state.dismissedScreens]);
  useEffect(() => { const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setTourOpen(false); setHelpOpen(false); } if (tourOpen && event.key === 'ArrowRight') setTourIndex(i => Math.min(i + 1, 2)); if (tourOpen && event.key === 'ArrowLeft') setTourIndex(i => Math.max(i - 1, 0)); }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close); }, [tourOpen]);
  const reset = useCallback(() => setState(initialState), []);
  const startTour = useCallback(() => { setTourIndex(0); setTourOpen(true); }, []);
  const progress = Math.round((state.completed.length / onboardingSteps.length) * 100);
  const value = useMemo(() => ({ state, complete, activate, reset, progress, startTour }), [state, complete, activate, reset, progress, startTour]);
  const help = screenHelp[pathname]; const next = onboardingSteps[state.currentStep];
  return <OnboardingContext.Provider value={value}>{children}
    {helpOpen && help ? <aside className="onboarding-context-help" aria-label={`Ajuda sobre ${help.title}`}><button className="onboarding-close" onClick={() => { setHelpOpen(false); setState(s => ({ ...s, dismissedScreens: Array.from(new Set([...s.dismissedScreens, pathname])) })); }} aria-label="Nunca mostrar novamente"><X size={16}/></button><span className="onboarding-eyebrow"><Sparkles size={14}/> Conheça este módulo</span><h2>{help.title}</h2><p>{help.text}</p><ul>{help.bullets.map(item => <li key={item}><Check size={15}/>{item}</li>)}</ul><small>Tempo de leitura: 30 segundos</small><div><Link href="/dashboard/academy">Ver exemplo</Link><button onClick={() => setHelpOpen(false)}>Próximo</button></div></aside> : null}
    {ready && next ? <aside className="onboarding-assistant" aria-label="Assistente Wazza"><button className="onboarding-help-toggle" onClick={() => setHelpOpen(v => !v)} aria-label="Abrir ajuda contextual"><HelpCircle size={19}/></button><span>Assistente Wazza</span><strong>Passo {state.currentStep + 1} de {onboardingSteps.length}</strong><div className="onboarding-progress"><i style={{ width: `${progress}%` }}/></div><b>{next.title}</b><p>{next.description}</p><Link href={getMissionRoute(next.id)} onClick={() => { if (next.id === 'whatsapp') activate(next.id); else if (next.id !== 'publish') complete(next.id); }}>{next.action}</Link></aside> : null}
    {tourOpen ? <Tour index={tourIndex} onClose={() => { setTourOpen(false); setState(s => ({ ...s, tourDismissed: true })); }} onNext={() => tourIndex === 2 ? setTourOpen(false) : setTourIndex(i => i + 1)} onBack={() => setTourIndex(i => Math.max(i - 1, 0))} /> : null}
  </OnboardingContext.Provider>;
}
function Tour({ index, onClose, onNext, onBack }: { index: number; onClose: () => void; onNext: () => void; onBack: () => void }) { const steps = [['Seu mapa de operação', 'Comece pelo checklist: ele adapta os próximos passos ao que você já fez.'], ['Aprenda no contexto', 'Cada módulo explica o problema que resolve, com exemplos práticos.'], ['Teste sem risco', 'Use o modo demonstração na Academy antes de conectar seu WhatsApp.']]; return <div className="onboarding-tour" role="dialog" aria-modal="false" aria-label="Tour do Wazza"><div className="onboarding-tour-spotlight"/><section><button className="onboarding-close" onClick={onClose} aria-label="Pular tour"><X size={18}/></button><span>{index + 1} de {steps.length}</span><h2>{steps[index][0]}</h2><p>{steps[index][1]}</p><footer><button onClick={onBack} disabled={!index}><ChevronLeft size={16}/> Voltar</button><button onClick={onNext}>{index === 2 ? 'Terminar' : 'Avançar'} <ChevronRight size={16}/></button></footer></section></div> }
