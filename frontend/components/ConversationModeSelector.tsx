import { ConversationMode } from '../lib/types';

type ConversationModeSelectorProps = {
  mode: ConversationMode;
  loading?: boolean;
  disabled?: boolean;
  onChange: (mode: ConversationMode) => void;
};

const MODE_OPTIONS: Array<{ value: ConversationMode; label: string; icon: string }> = [
  { value: 'human', label: 'Humano', icon: '🟢' },
  { value: 'bot', label: 'Bot', icon: '⚙️' },
  { value: 'ai', label: 'IA', icon: '🤖' }
];

export default function ConversationModeSelector({
  mode,
  loading = false,
  disabled = false,
  onChange
}: ConversationModeSelectorProps) {
  return (
    <div className="wa-mode-selector" role="group" aria-label="Modo da conversa">
      {MODE_OPTIONS.map((option) => {
        const isActive = mode === option.value;

        return (
          <button
            key={option.value}
            type="button"
            className={`wa-mode-button ${option.value} ${isActive ? 'active' : ''}`}
            onClick={() => onChange(option.value)}
            disabled={disabled || loading}
            aria-pressed={isActive}
          >
            <span aria-hidden="true">{option.icon}</span>
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
