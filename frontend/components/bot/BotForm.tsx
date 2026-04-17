import { FormEvent } from 'react';

type MatchType = 'contains' | 'exact';

type BotFormProps = {
  trigger: string;
  response: string;
  matchType: MatchType;
  saving: boolean;
  onTriggerChange: (value: string) => void;
  onResponseChange: (value: string) => void;
  onMatchTypeChange: (value: MatchType) => void;
  onSubmit: () => Promise<void>;
};

export default function BotForm({
  trigger,
  response,
  matchType,
  saving,
  onTriggerChange,
  onResponseChange,
  onMatchTypeChange,
  onSubmit
}: BotFormProps) {
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit();
  }

  const isDisabled = saving || !trigger.trim() || !response.trim();

  return (
    <article className="products-form-card">
      <h2>Criar regra</h2>
      <form onSubmit={handleSubmit} className="products-form">
        <label htmlFor="bot-trigger">Trigger</label>
        <input
          id="bot-trigger"
          value={trigger}
          onChange={(event) => onTriggerChange(event.target.value)}
          placeholder="Ex: preço"
        />

        <label htmlFor="bot-response">Resposta</label>
        <textarea
          id="bot-response"
          value={response}
          onChange={(event) => onResponseChange(event.target.value)}
          placeholder="Digite a resposta do bot"
        />

        <label htmlFor="bot-match-type">Tipo de match</label>
        <select
          id="bot-match-type"
          value={matchType}
          onChange={(event) => onMatchTypeChange(event.target.value as MatchType)}
          className="bot-form-select"
        >
          <option value="contains">contains</option>
          <option value="exact">exact</option>
        </select>

        <div className="products-form-actions">
          <button type="submit" className="primary-button" disabled={isDisabled}>
            {saving ? 'Criando...' : 'Criar regra'}
          </button>
        </div>
      </form>
    </article>
  );
}
