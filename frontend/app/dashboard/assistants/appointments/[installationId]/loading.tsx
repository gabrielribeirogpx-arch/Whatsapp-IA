export default function Loading() {
  return <main className="appointment-page" aria-label="Carregando assistente"><div className="appointment-skeleton appointment-skeleton-title" />{[1, 2, 3].map((item) => <div className="appointment-skeleton appointment-skeleton-card" key={item} />)}</main>;
}
