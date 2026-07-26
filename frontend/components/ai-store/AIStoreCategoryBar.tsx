import type { AIStoreCategoryValue } from './types';
const categories: AIStoreCategoryValue[] = ['Todos', 'Fluxos', 'Híbridos', 'AI Systems', 'Business Kits', 'Aprender'];
export default function AIStoreCategoryBar({ selected, onSelect }: { selected: AIStoreCategoryValue; onSelect: (value: AIStoreCategoryValue) => void }) {
  return <div className="ai-store-category-list" aria-label="Tipos do Marketplace">{categories.map((value) => <button key={value} type="button" className={selected === value ? 'active' : ''} onClick={() => onSelect(value)}>{value}</button>)}</div>;
}
