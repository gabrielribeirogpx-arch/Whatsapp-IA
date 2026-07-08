type AIStoreSearchProps = {
  value: string;
  onChange: (value: string) => void;
};

export default function AIStoreSearch({ value, onChange }: AIStoreSearchProps) {
  return (
    <label className="ai-store-search" aria-label="Buscar sistemas inteligentes">
      <span aria-hidden="true">🔎</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Buscar por nome, descrição, integração ou capacidade..."
      />
    </label>
  );
}
