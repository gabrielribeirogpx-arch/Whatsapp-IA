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
  id: string;
  label: string;
  handleId: string;
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
    isStart?: boolean;
    metadata?: Record<string, unknown>;
    onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
    is_terminal?: boolean;
    hasValidationError?: boolean;
  };
};

export type FlowEdgePayload = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  label?: string;
  data?: {
    condition?: string;
    sourceHandle?: string;
  };
};

export type FlowGraphPayload = {
  flow_id?: string;
  version_id?: string | null;
  source?: 'version' | 'fallback' | 'empty' | string;
  nodes: FlowNodePayload[];
  edges: FlowEdgePayload[];
};

export type FlowItem = {
  id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  trigger_type: 'keyword' | 'default' | string;
  trigger_value?: string | null;
  version: number;
  created_at?: string | null;
  updated_at?: string | null;
};

export type FlowVersionItem = {
  id: string;
  flow_id: string;
  version: number;
  version_number?: number;
  created_at?: string | null;
  is_active?: boolean;
  is_current: boolean;
};

export type FlowPayload = {
  name: string;
  description?: string;
  trigger_type: 'keyword' | 'default';
  trigger_value?: string;
  is_active?: boolean;
};

export type DeleteFlowResponse = {
  success: boolean;
  mode: 'hard_delete' | 'soft_delete' | string;
};

export type FlowAnalytics = {
  flow_id: string;
  flow_name: string;
  period: '24h' | '7d' | '30d' | '90d' | string;
  summary: { entries: number; messages_sent: number; completed: number; conversion_rate: number; dropoff_rate: number; avg_time_seconds: number; avg_messages_per_user: number; };
  funnel: Array<{ node_id: string; node_label: string; node_type: string; entries: number; exits: number; dropoff_rate: number; conversion_to_next_rate: number; avg_time_seconds: number; }>;
  top_dropoffs: Array<{ node_id: string; node_label: string; node_type: string; entries: number; exits: number; dropoff_rate: number; conversion_to_next_rate: number; avg_time_seconds: number; }>;
  common_replies: Array<{ reply: string; count: number; rate: number }>;
  timeline: Array<{ date: string; entries: number; messages_sent: number; completed: number }>;
  insights: Array<{ type: 'warning' | 'info' | 'success' | string; title: string; message: string; node_id?: string | null }>;
};

export type SystemSettings = {
  token: string | null;
  phone_number_id: string;
  webhook_url: string | null;
  webhook_status: string;
  system_name: string;
  language: string;
};

export type SystemSettingsPayload = {
  token: string | null;
  phone_number_id: string;
  webhook_url: string | null;
  webhook_status: string;
  system_name: string;
  language: string;
};
