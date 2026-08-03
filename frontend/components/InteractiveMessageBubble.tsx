import { InteractiveMessageType } from '../lib/types';
import { useDeveloperMode } from '../hooks/useDeveloperMode';

export type InteractiveTechnicalDetails = {
  payload?: string | null;
  type?: InteractiveMessageType | null;
  id?: string | null;
  flow?: string | null;
  node?: string | null;
  origin?: string | null;
  technicalTimestamp?: string | null;
  commitSha?: string | null;
  runtime?: string | null;
};

type InteractiveMessageBubbleProps = {
  title: string;
  type?: InteractiveMessageType | null;
  payload?: string | null;
  technicalDetails?: InteractiveTechnicalDetails;
  variant?: 'conversation' | 'preview';
};

const presentation = {
  button_reply: { icon: '🤖', label: 'Resposta interativa' },
  list_reply: { icon: '📋', label: 'Resposta da lista' },
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
  technicalDetails,
  variant = 'conversation',
}: InteractiveMessageBubbleProps) {
  const normalizedType = normalizeInteractiveType(type) ?? 'interactive';
  const meta = presentation[normalizedType];
  const developerMode = useDeveloperMode();
  const details: InteractiveTechnicalDetails = {
    payload,
    type: normalizedType,
    id: payload,
    ...technicalDetails,
  };
  const technicalFields = [
    ['Payload', details.payload],
    ['Tipo', details.type],
    ['ID', details.id],
    ['Flow', details.flow],
    ['Node', details.node],
    ['Origem', details.origin],
    ['Timestamp técnico', details.technicalTimestamp],
    ['Commit SHA', details.commitSha],
    ['Runtime', details.runtime],
  ].filter((field): field is [string, string] => Boolean(field[1]));

  return (
    <div className={`wa-interactive-message wa-interactive-message--${variant}`}>
      <div className="wa-interactive-message-kind">
        <span aria-hidden="true">{meta.icon}</span>
        <strong>{meta.label}</strong>
      </div>
      <p className="wa-interactive-message-title">{title}</p>
      {variant === 'conversation' && developerMode && technicalFields.length > 0 ? (
        <details className="wa-interactive-message-details">
          <summary>🔧 Detalhes técnicos</summary>
          <dl>
            {technicalFields.map(([label, value]) => (
              <div key={label}><dt>{label}</dt><dd><code>{value}</code></dd></div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}
