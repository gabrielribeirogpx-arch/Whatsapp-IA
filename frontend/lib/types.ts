export type Conversation = {
  id: string;
  tenant_id: string;
  contact_id?: string | null;
  phone: string;
  name: string | null;
  avatar_url?: string | null;
  stage?: string;
  score?: number;
  mode: 'human' | 'bot' | 'ai' | string;
  last_message: string;
  updated_at: string;
};

export type ConversationMode = 'human' | 'bot' | 'ai';

export type Message = {
  id: string;
  content: string;
  role: string;
  created_at: string;
};

export type TenantSession = {
  tenant_id: string;
  token: string;
  slug?: string;
};


export type BotMatchType = 'contains' | 'exact';

export type BotRule = {
  id: string;
  tenant_id: string;
  trigger: string;
  response: string;
  match_type: BotMatchType;
  created_at?: string;
  updated_at?: string;
};

export type BotRulePayload = {
  trigger: string;
  response: string;
  match_type: BotMatchType;
};

export type Contact = {
  id: string;
  tenant_id?: string;
  name: string | null;
  phone: string;
  avatarUrl?: string | null;
  stage?: string;
  score?: number;
  lastMessageAt?: string | null;
  lastMessage: string;
  isOnline?: boolean;
  isTyping?: boolean;
  status?: string;
};

export type ChatMessage = {
  id: string;
  text: string;
  fromMe: boolean;
  time: string;
};

export type SendMessagePayload = {
  to: string;
  message: string;
};

export type CRMContact = {
  id: string;
  tenant_id: string;
  phone: string;
  name: string | null;
  avatar_url?: string | null;
  stage: string;
  score: number;
  last_message_at?: string | null;
  last_message?: string | null;
  created_at: string;
};


export type Product = {
  id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  price?: string | null;
  benefits?: string | null;
  objections?: string | null;
  target_customer?: string | null;
  created_at: string;
  updated_at: string;
};

export type ProductPayload = {
  name: string;
  description?: string;
  price?: string;
  benefits?: string;
  objections?: string;
  target_customer?: string;
};

export type KnowledgeItem = {
  id: string;
  tenant_id: string;
  title: string;
  content: string;
  created_at: string;
};

export type KnowledgePayload = {
  title: string;
  content: string;
};

export type KnowledgeUploadResult = {
  source: string;
  chunks_created: number;
};


export type KnowledgeCrawlPayload = {
  url: string;
  depth?: 1 | 2;
};

export type KnowledgeCrawlResult = {
  source: string;
  pages_collected: number;
  chunks_created: number;
};


export type PipelineTemperature = 'hot' | 'warm' | 'cold';

export type PipelineLead = {
  id: string;
  name: string | null;
  phone: string;
  last_message: string | null;
  temperature: PipelineTemperature;
  score: number;
  stage_id: string | null;
  last_interaction: string | null;
};

export type PipelineStage = {
  id: string;
  name: string;
  position: number;
  leads: PipelineLead[];
};


export type FlowChoiceButton = {
  label: string;
  next?: string;
};

export type FlowNodePayload = {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label?: string;
    content?: string;
    buttons?: FlowChoiceButton[];
    condition?: string;
    action?: string;
    metadata?: Record<string, unknown>;
    onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
  };
};

export type FlowEdgePayload = {
  id: string;
  source: string;
  target: string;
  label?: string;
  data?: {
    condition?: string;
  };
};

export type FlowGraphPayload = {
  nodes: FlowNodePayload[];
  edges: FlowEdgePayload[];
};
