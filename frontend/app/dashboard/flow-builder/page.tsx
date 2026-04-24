import FlowBuilderClient from './FlowBuilderClient';

type FlowBuilderPageProps = {
  searchParams?: {
    flow_id?: string;
  };
};

export default function FlowBuilderPage({ searchParams }: FlowBuilderPageProps) {
  const flowId = searchParams?.flow_id;
  return <FlowBuilderClient flowId={flowId} />;
}
