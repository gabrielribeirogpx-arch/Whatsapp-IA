'use client';

import { useEffect, useMemo, useState } from 'react';
import { Check, Plus, Store, X } from 'lucide-react';
import { publishFlowAsMarketplaceTemplate } from '@/lib/api';

type Props = {
  flowId: string;
  flowName: string;
  nodes: Array<{ id: string; type?: string; data?: Record<string, unknown> }>;
  onClose: () => void;
  onPublished: (message: string) => void;
};

type TemplateKind = 'flow' | 'appointment_assistant';

function nodeCaption(node: Props['nodes'][number]): string {
  const data = node.data || {};
  const label = String(data.label || data.tool_name || data.action_type || node.type || 'Node');
  const detail = String(data.content || data.message || data.text || data.reason || '').trim();
  return `${node.type || 'node'} — ${label}${detail ? ` — ${detail.slice(0, 70)}` : ''}`;
}

const CATEGORIES = ['Atendimento', 'Vendas', 'Marketing', 'Suporte', 'Operações', 'Agendamentos'];
const MODALITIES = ['Sem IA', 'Híbrido', 'IA Completa', 'Sistema Completo'];

function readableError(error: unknown): string {
  const message = error instanceof Error ? error.message : 'Não foi possível publicar o template.';
  if (message.includes('published_flow_not_found') || message.includes('published_snapshot_not_found')) {
    return 'Ative o fluxo para criar uma versão publicada antes de enviá-lo ao Marketplace.';
  }
  if (message.includes('template_version_already_exists')) return 'Esta versão já foi publicada para o template.';
  if (message.includes('official_template_forbidden') || message.includes('403')) return 'Apenas owners e administradores podem publicar templates.';
  return message.replace(/^HTTP \d+:\s*/, '') || 'Não foi possível publicar o template.';
}

export default function PublishMarketplaceTemplateModal({ flowId, flowName, nodes, onClose, onPublished }: Props) {
  const [name, setName] = useState(flowName);
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [modality, setModality] = useState(MODALITIES[0]);
  const [version, setVersion] = useState('1.0.0');
  const [tagInput, setTagInput] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [isPublishing, setIsPublishing] = useState(false);
  const [templateKind, setTemplateKind] = useState<TemplateKind>('flow');
  const [clinicNodeId, setClinicNodeId] = useState('');
  const [clinicField, setClinicField] = useState<'data.message' | 'data.content' | 'data.text'>('data.content');
  const [servicesNodeId, setServicesNodeId] = useState('');
  const [calendarNodeIds, setCalendarNodeIds] = useState<string[]>([]);
  const [handoffNodeIds, setHandoffNodeIds] = useState<string[]>([]);

  const messageNodes = nodes.filter((node) => node.type === 'message');
  const choiceNodes = nodes.filter((node) => node.type === 'choice');
  const calendarNodes = nodes.filter((node) => node.type === 'mcp_tool');
  const handoffNodes = nodes.filter((node) => node.type === 'action');
  const assistantComplete = Boolean(clinicNodeId && servicesNodeId && calendarNodeIds.length && handoffNodeIds.length);

  const canPublish = useMemo(
    () => name.trim().length > 0 && description.trim().length > 0 && category.length > 0 && modality.length > 0 && version.trim().length > 0 && (templateKind === 'flow' || assistantComplete),
    [assistantComplete, category, description, modality, name, templateKind, version],
  );

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => event.key === 'Escape' && !isPublishing && onClose();
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isPublishing, onClose]);

  const addTag = () => {
    const value = tagInput.trim().replace(/^#/, '');
    if (value && !tags.includes(value) && tags.length < 10) setTags((current) => [...current, value]);
    setTagInput('');
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canPublish || isPublishing) return;
    setError('');
    setIsPublishing(true);
    try {
      const result = await publishFlowAsMarketplaceTemplate(flowId, {
        name: name.trim(), description: description.trim(), category, modality, tags, version: version.trim(), template_kind: templateKind,
        ...(templateKind === 'appointment_assistant' ? { assistant_mapping: {
          clinic_name_node_id: clinicNodeId, clinic_name_field: clinicField,
          services_node_id: servicesNodeId, calendar_node_ids: calendarNodeIds,
          handoff_node_ids: handoffNodeIds,
        } } : {}),
      });
      onPublished(`Template “${result.name}” v${result.version} publicado no Marketplace.`);
      onClose();
    } catch (publishError) {
      setError(readableError(publishError));
    } finally {
      setIsPublishing(false);
    }
  };

  return (
    <div className="marketplace-publish-backdrop" role="presentation" onMouseDown={() => !isPublishing && onClose()}>
      <form className="marketplace-publish-modal" role="dialog" aria-modal="true" aria-labelledby="marketplace-publish-title" onMouseDown={(event) => event.stopPropagation()} onSubmit={submit}>
        <header>
          <div className="marketplace-publish-icon"><Store size={22} /></div>
          <div><span>Marketplace</span><h2 id="marketplace-publish-title">Publicar como Template</h2><p>Compartilhe a versão ativa deste fluxo como um template instalável.</p></div>
          <button type="button" aria-label="Fechar" onClick={onClose} disabled={isPublishing}><X size={20} /></button>
        </header>

        <div className="marketplace-publish-body">
          <label>Nome<input autoFocus maxLength={200} required value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex.: Qualificação de leads" /></label>
          <label>Descrição<textarea maxLength={1000} required rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Explique o objetivo, o público e o resultado deste fluxo." /></label>
          <fieldset className="marketplace-template-kind"><legend>Tipo de template</legend>
            <label><input type="radio" name="template-kind" checked={templateKind === 'flow'} onChange={() => setTemplateKind('flow')} /><span><strong>Template de fluxo</strong><small>Instala o fluxo para edição no Flow Builder.</small></span></label>
            <label><input type="radio" name="template-kind" checked={templateKind === 'appointment_assistant'} onChange={() => setTemplateKind('appointment_assistant')} /><span><strong>Assistente de Agendamento configurável</strong><small>Abre a configuração comercial de clínica, serviços, agenda e transferência.</small></span></label>
          </fieldset>
          {templateKind === 'appointment_assistant' && <section className="marketplace-assistant-map" aria-label="Mapeamento do assistente">
            <p>Indique explicitamente o papel de cada etapa. A publicação não altera seu fluxo original.</p>
            <label>Mensagem com nome da clínica<select value={clinicNodeId} onChange={(event) => setClinicNodeId(event.target.value)}><option value="">Selecione uma mensagem</option>{messageNodes.map((node) => <option key={node.id} value={node.id}>{nodeCaption(node)}</option>)}</select></label>
            <label>Campo da mensagem<select value={clinicField} onChange={(event) => setClinicField(event.target.value as typeof clinicField)}><option value="data.content">Conteúdo</option><option value="data.message">Mensagem</option><option value="data.text">Texto</option></select></label>
            <label>Escolha dos serviços<select value={servicesNodeId} onChange={(event) => setServicesNodeId(event.target.value)}><option value="">Selecione uma escolha</option>{choiceNodes.map((node) => <option key={node.id} value={node.id}>{nodeCaption(node)}</option>)}</select></label>
            <div><strong>Etapas do Google Calendar</strong><small>Selecione todas as etapas usadas para disponibilidade, criação, busca ou atualização.</small>{calendarNodes.map((node) => <label key={node.id} className="marketplace-node-check"><input type="checkbox" checked={calendarNodeIds.includes(node.id)} onChange={(event) => setCalendarNodeIds((current) => event.target.checked ? [...current, node.id] : current.filter((id) => id !== node.id))} /><span>{nodeCaption(node)}</span></label>)}</div>
            <div><strong>Transferência humana</strong>{handoffNodes.map((node) => <label key={node.id} className="marketplace-node-check"><input type="checkbox" checked={handoffNodeIds.includes(node.id)} onChange={(event) => setHandoffNodeIds((current) => event.target.checked ? [...current, node.id] : current.filter((id) => id !== node.id))} /><span>{nodeCaption(node)}</span></label>)}</div>
          </section>}
          <div className="marketplace-publish-grid">
            <label>Categoria<select value={category} onChange={(event) => setCategory(event.target.value)}>{CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label>
            <label>Modalidade<select value={modality} onChange={(event) => setModality(event.target.value)}>{MODALITIES.map((item) => <option key={item}>{item}</option>)}</select></label>
          </div>
          <label>Tags<div className="marketplace-tag-input"><input value={tagInput} onChange={(event) => setTagInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ',') { event.preventDefault(); addTag(); } }} placeholder="Digite uma tag e pressione Enter" /><button type="button" onClick={addTag} disabled={!tagInput.trim() || tags.length >= 10}><Plus size={16} />Adicionar</button></div></label>
          {tags.length > 0 && <div className="marketplace-tags" aria-label="Tags selecionadas">{tags.map((tag) => <button type="button" key={tag} onClick={() => setTags((current) => current.filter((item) => item !== tag))}>#{tag}<X size={13} /></button>)}</div>}
          <label className="marketplace-version">Versão<input maxLength={32} required value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.0.0" /><small>Use uma nova versão a cada atualização do template.</small></label>
          {error && <div className="marketplace-publish-error" role="alert">{error}</div>}
        </div>

        <footer><button type="button" className="flow-top-btn flow-top-btn-neutral" onClick={onClose} disabled={isPublishing}>Cancelar</button><button type="submit" className="flow-top-btn flow-top-btn-primary" disabled={!canPublish || isPublishing}>{isPublishing ? 'Publicando…' : <><Check size={16} />Publicar</>}</button></footer>
      </form>
    </div>
  );
}
