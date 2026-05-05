import FlowBuilderClient from './FlowBuilderClient';

type FlowBuilderPageProps = {
  searchParams?: {
    flow_id?: string;
  };
};

export default function FlowBuilderPage({ searchParams }: FlowBuilderPageProps) {
  const flowId = searchParams?.flow_id;

  return (
    <main className="h-screen w-full overflow-hidden">
      <FlowBuilderClient flowId={flowId} />
    </main>
  );
}
