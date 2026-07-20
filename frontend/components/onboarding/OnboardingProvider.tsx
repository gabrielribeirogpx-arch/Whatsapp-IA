'use client';

import Link from 'next/link';
import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Check, ChevronLeft, ChevronRight, HelpCircle, Sparkles, X } from 'lucide-react';

export type OnboardingStep = { id: string; title: string; description: string; href: string; action: string };
export type TutorialState = { completed: string[]; dismissedScreens: string[]; tourDismissed: boolean };
const STORAGE_KEY = 'wazza:onboarding:tenant:default';
export const onboardingSteps: OnboardingStep[] = [
  { id: 'company', title: 'Criar empresa', description: 'Defina a operação que será atendida.', href: '/dashboard/settings', action: 'Abrir configurações' },
  { id: 'whatsapp', title: 'Conectar WhatsApp', description: 'Conecte seu canal para receber mensagens reais.', href: '/dashboard/settings?tab=whatsapp-business', action: 'Conectar agora' },
  { id: 'flow', title: 'Criar primeiro fluxo', description: 'Monte a automação que orienta cada conversa.', href: '/dashboard/flows', action: 'Criar fluxo' },
  { id: 'message', title: 'Receber primeira mensagem', description: 'Use a demonstração ou seu WhatsApp conectado.', href: '/dashboard/inbox', action: 'Abrir Inbox' },
  { id: 'inbox', title: 'Testar Inbox', description: 'Veja, responda e encaminhe uma conversa.', href: '/dashboard/inbox', action: 'Testar Inbox' },
  { id: 'pipeline', title: 'Criar Pipeline', description: 'Organize oportunidades em etapas comerciais.', href: '/dashboard/pipeline', action: 'Abrir Pipeline' },
  { id: 'ai', title: 'Configurar IA', description: 'Defina como a IA ajuda sua equipe.', href: '/dashboard/ai/playground', action: 'Configurar IA' },
  { id: 'publish', title: 'Publicar automação', description: 'Ative o fluxo para colocá-lo em operação.', href: '/dashboard/flows', action: 'Publicar fluxo' },
  { id: 'team', title: 'Convidar equipe', description: 'Traga operadores para atender juntos.', href: '/dashboard/settings', action: 'Convidar equipe' },
];
const screenHelp: Record<string, { title: string; text: string; bullets: string[] }> = {
  '/dashboard': { title: 'Dashboard', text: 'Visão geral da sua operação.', bullets: ['Acompanhe conversas e resultados', 'Encontre próximos passos sugeridos'] },
  '/dashboard/inbox': { title: 'Inbox', text: 'Aqui chegam todas as mensagens dos seus clientes.', bullets: ['Responda manualmente ou com IA', 'Transfira para operadores e consulte o CRM'] },
  '/dashboard/clients': { title: 'CRM', text: 'Armazena informações e o histórico de cada cliente.', bullets: ['Registre tags e observações', 'Use dados para personalizar o atendimento'] },
  '/dashboard/pipeline': { title: 'Pipeline', text: 'Organiza oportunidades até a venda.', bullets: ['Arraste leads entre etapas', 'Descubra onde sua operação perde oportunidades'] },
  '/dashboard/flows': { title: 'Fluxos', text: 'Automatiza processos e respostas.', bullets: ['Combine mensagens, condições e IA', 'Publique quando estiver pronto'] },
  '/dashboard/observability': { title: 'Observabilidade', text: 'Mostra tudo que aconteceu em cada execução.', bullets: ['Siga mensagens, fluxo, IA e resposta', 'Use traces para investigar e melhorar'] },
};
type ContextValue = { state: TutorialState; complete: (id: string) => void; reset: () => void; progress: number; startTour: () => void };
const OnboardingContext = createContext<ContextValue | null>(null);
export const useOnboarding = () => { const value = useContext(OnboardingContext); if (!value) throw new Error('useOnboarding must be used inside OnboardingProvider'); return value; };

function readState(): TutorialState { try { return { completed: [], dismissedScreens: [], tourDismissed: false, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }; } catch { return { completed: [], dismissedScreens: [], tourDismissed: false }; } }
export function OnboardingProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [state, setState] = useState<TutorialState>({ completed: [], dismissedScreens: [], tourDismissed: false });
  const [ready, setReady] = useState(false); const [helpOpen, setHelpOpen] = useState(false); const [tourOpen, setTourOpen] = useState(false); const [tourIndex, setTourIndex] = useState(0);
  useEffect(() => { setState(readState()); setReady(true); }, []);
  useEffect(() => { if (ready) localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }, [state, ready]);
  useEffect(() => { setHelpOpen(Boolean(ready && screenHelp[pathname] && !state.dismissedScreens.includes(pathname))); }, [pathname, ready]);
  useEffect(() => { const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setTourOpen(false); setHelpOpen(false); } if (tourOpen && event.key === 'ArrowRight') setTourIndex(i => Math.min(i + 1, 2)); if (tourOpen && event.key === 'ArrowLeft') setTourIndex(i => Math.max(i - 1, 0)); }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close); }, [tourOpen]);
  const complete = useCallback((id: string) => setState(old => old.completed.includes(id) ? old : { ...old, completed: [...old.completed, id] }), []);
  const reset = useCallback(() => setState({ completed: [], dismissedScreens: [], tourDismissed: false }), []);
  const startTour = useCallback(() => { setTourIndex(0); setTourOpen(true); }, []);
  const progress = Math.round((state.completed.length / onboardingSteps.length) * 100);
  const value = useMemo(() => ({ state, complete, reset, progress, startTour }), [state, complete, reset, progress, startTour]);
  const help = screenHelp[pathname]; const next = onboardingSteps.find(step => !state.completed.includes(step.id));
  return <OnboardingContext.Provider value={value}>{children}
    {helpOpen && help ? <aside className="onboarding-context-help" aria-label={`Ajuda sobre ${help.title}`}><button className="onboarding-close" onClick={() => { setHelpOpen(false); setState(s => ({ ...s, dismissedScreens: Array.from(new Set([...s.dismissedScreens, pathname])) })); }} aria-label="Nunca mostrar novamente"><X size={16}/></button><span className="onboarding-eyebrow"><Sparkles size={14}/> Conheça este módulo</span><h2>{help.title}</h2><p>{help.text}</p><ul>{help.bullets.map(item => <li key={item}><Check size={15}/>{item}</li>)}</ul><small>Tempo de leitura: 30 segundos</small><div><Link href="/dashboard/academy">Ver exemplo</Link><button onClick={() => setHelpOpen(false)}>Próximo</button></div></aside> : null}
    {ready && next ? <aside className="onboarding-assistant" aria-label="Assistente Wazza"><button className="onboarding-help-toggle" onClick={() => setHelpOpen(v => !v)} aria-label="Abrir ajuda contextual"><HelpCircle size={19}/></button><span>Assistente Wazza</span><strong>Passo {state.completed.length + 1} de {onboardingSteps.length}</strong><div className="onboarding-progress"><i style={{ width: `${progress}%` }}/></div><b>{next.title}</b><p>{next.description}</p><Link href={next.href} onClick={() => complete(next.id)}>{next.action}</Link></aside> : null}
    {tourOpen ? <Tour index={tourIndex} onClose={() => { setTourOpen(false); setState(s => ({ ...s, tourDismissed: true })); }} onNext={() => tourIndex === 2 ? setTourOpen(false) : setTourIndex(i => i + 1)} onBack={() => setTourIndex(i => Math.max(i - 1, 0))} /> : null}
  </OnboardingContext.Provider>;
}
function Tour({ index, onClose, onNext, onBack }: { index: number; onClose: () => void; onNext: () => void; onBack: () => void }) { const steps = [['Seu mapa de operação', 'Comece pelo checklist: ele adapta os próximos passos ao que você já fez.'], ['Aprenda no contexto', 'Cada módulo explica o problema que resolve, com exemplos práticos.'], ['Teste sem risco', 'Use o modo demonstração na Academy antes de conectar seu WhatsApp.']]; return <div className="onboarding-tour" role="dialog" aria-modal="false" aria-label="Tour do Wazza"><div className="onboarding-tour-spotlight"/><section><button className="onboarding-close" onClick={onClose} aria-label="Pular tour"><X size={18}/></button><span>{index + 1} de {steps.length}</span><h2>{steps[index][0]}</h2><p>{steps[index][1]}</p><footer><button onClick={onBack} disabled={!index}><ChevronLeft size={16}/> Voltar</button><button onClick={onNext}>{index === 2 ? 'Terminar' : 'Avançar'} <ChevronRight size={16}/></button></footer></section></div> }
