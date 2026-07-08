import type { AIStoreCategoryValue } from './types';

const AI_STORE_CATEGORIES: Array<{ value: AIStoreCategoryValue; label: string }> = [
  { value: 'Recomendados', label: '⭐ Recomendados' },
  { value: 'Produtividade', label: '📅 Produtividade' },
  { value: 'Atendimento', label: '💬 Atendimento' },
  { value: 'Vendas', label: '💰 Comercial' },
  { value: 'Conhecimento', label: '📚 Conhecimento' },
  { value: 'Automação', label: '⚙ Automação' },
  { value: 'Personalizados', label: '🧩 Personalizados' },
];

type AIStoreCategoryBarProps = {
  selected: AIStoreCategoryValue;
  onSelect: (category: AIStoreCategoryValue) => void;
};

export default function AIStoreCategoryBar({ selected, onSelect }: AIStoreCategoryBarProps) {
  return (
    <div className="ai-store-category-list" aria-label="Categorias da AI Store">
      {AI_STORE_CATEGORIES.map((category) => (
        <button
          key={category.value}
          type="button"
          className={category.value === selected ? 'active' : ''}
          onClick={() => onSelect(category.value)}
        >
          {category.label}
        </button>
      ))}
    </div>
  );
}
