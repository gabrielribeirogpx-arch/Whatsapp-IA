'use client';

import { useEffect, useMemo, useState } from 'react';
import { Check, Plus, Store, X } from 'lucide-react';
import { publishFlowAsMarketplaceTemplate } from '@/lib/api';

type Props = {
  flowId: string;
  flowName: string;
  onClose: () => void;
  onPublished: (message: string) => void;
};

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

export default function PublishMarketplaceTemplateModal({ flowId, flowName, onClose, onPublished }: Props) {
  const [name, setName] = useState(flowName);
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [modality, setModality] = useState(MODALITIES[0]);
  const [version, setVersion] = useState('1.0.0');
  const [tagInput, setTagInput] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [isPublishing, setIsPublishing] = useState(false);

  const canPublish = useMemo(
    () => name.trim().length > 0 && description.trim().length > 0 && category.length > 0 && modality.length > 0 && version.trim().length > 0,
    [category, description, modality, name, version],
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
        name: name.trim(), description: description.trim(), category, modality, tags, version: version.trim(),
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
