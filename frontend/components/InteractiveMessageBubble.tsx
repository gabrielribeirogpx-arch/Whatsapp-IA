import { InteractiveMessageType } from '../lib/types';

type InteractiveMessageBubbleProps = {
  title: string;
  type?: InteractiveMessageType | null;
  payload?: string | null;
  variant?: 'conversation' | 'preview';
};

const presentation = {
  button_reply: { icon: '🖱️', label: 'Botão selecionado' },
  list_reply: { icon: '📋', label: 'Opção da lista' },
  interactive: { icon: '🖱️', label: 'Resposta interativa' },
} satisfies Record<InteractiveMessageType, { icon: string; label: string }>;

export function normalizeInteractiveType(type?: string | null): InteractiveMessageType | null {
  const normalized = type?.trim().toLowerCase();
  if (normalized === 'button_reply' || normalized === 'list_reply' || normalized === 'interactive') {
    return normalized;
  }
  return null;
}

export default function InteractiveMessageBubble({
  title,
  type,
  payload,
  variant = 'conversation',
}: InteractiveMessageBubbleProps) {
  const normalizedType = normalizeInteractiveType(type) ?? 'interactive';
  const meta = presentation[normalizedType];

  return (
    <div className={`wa-interactive-message wa-interactive-message--${variant}`}>
      <div className="wa-interactive-message-kind">
        <span aria-hidden="true">{meta.icon}</span>
        <strong>{meta.label}</strong>
      </div>
      <p className="wa-interactive-message-title">{title}</p>
      {variant === 'conversation' && payload ? (
        <details className="wa-interactive-message-details">
          <summary>ⓘ Ver detalhes</summary>
          <div>
            <span>Payload interno</span>
            <code>{payload}</code>
            <dl>
              <div><dt>Tipo:</dt><dd>{normalizedType}</dd></div>
              <div><dt>ID:</dt><dd><code>{payload}</code></dd></div>
            </dl>
          </div>
        </details>
      ) : null}
    </div>
  );
}
