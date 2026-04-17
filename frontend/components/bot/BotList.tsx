import { BotRule } from '../../lib/types';

type BotListProps = {
  rules: BotRule[];
  loading: boolean;
  deletingId: string | null;
  onDelete: (ruleId: string) => Promise<void>;
};

export default function BotList({ rules, loading, deletingId, onDelete }: BotListProps) {
  if (loading) {
    return (
      <article className="products-list-card">
        <h2>Regras cadastradas</h2>
        <p>Carregando...</p>
      </article>
    );
  }

  return (
    <article className="products-list-card">
      <h2>Regras cadastradas</h2>
      <div className="bot-rules-table-wrap">
        <table className="crm-table">
          <thead>
            <tr>
              <th>Trigger</th>
              <th>Tipo</th>
              <th>Resposta</th>
              <th>Ação</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id}>
                <td>{rule.trigger}</td>
                <td>{rule.match_type}</td>
                <td>{rule.response}</td>
                <td>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => onDelete(rule.id)}
                    disabled={deletingId === rule.id}
                  >
                    {deletingId === rule.id ? 'Excluindo...' : 'Deletar'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!rules.length ? <p className="empty-state">Nenhuma regra criada até o momento.</p> : null}
    </article>
  );
}
