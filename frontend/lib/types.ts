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
  assigned_user_id?: string | null;
  assigned_user_name?: string | null;
  status?: string | null;
  unread_count?: number;
  last_message: string;
  updated_at: string;
};

export type ConversationMode = 'human' | 'bot' | 'ai';

export type Message = {
  id: string;
  content: string;
  role: string;
  created_at: string;
  media_url?: string | null;
  media_type?: string | null;
  attachment_url?: string | null;
  attachment_type?: string | null;
  file_url?: string | null;
  file_type?: string | null;
  caption?: string | null;
  filename?: string | null;
};

export type AccountProfile = {
  id: string;
  name: string;
  full_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  display_name?: string | null;
  username?: string | null;
  email: string;
  avatar_url?: string | null;
  company?: string | null;
  job_title?: string | null;
  role: string;
};

export type AccountPreferences = {
  language: string;
  timezone: string;
  email_notifications: boolean;
  whatsapp_notifications: boolean;
};

export type AccountSecurity = {
  last_login_at?: string | null;
  last_login_ip?: string | null;
  active_sessions_count: number;
  blocked_login_attempts: number;
  turnstile_status: string;
  protection_status: string;
  active_sessions: Array<{ id: string; device: string; ip_address?: string | null; location?: string | null; user_agent?: string | null; last_seen_at?: string | null; created_at?: string | null; revoked_at?: string | null; status: string; is_current?: boolean }>;
  history: Array<{ event: string; description?: string | null; created_at?: string | null }>;
  mfa_status: string;
};

export type AuditLog = {
  id: string;
  tenant_id?: string | null;
  user_id?: string | null;
  user_name?: string | null;
  user_email?: string | null;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  metadata_json: Record<string, unknown>;
  ip_address?: string | null;
  user_agent?: string | null;
  created_at?: string | null;
};

export type AccountMe = {
  profile: AccountProfile;
  preferences: AccountPreferences;
  security: AccountSecurity;
};

export type WorkspaceUser = {
  id: string;
  name: string;
  full_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  display_name?: string | null;
  username?: string | null;
  email: string;
  role: string;
  status: string;
  last_access_at?: string | null;
};

export type TenantSession = {
  tenant_id: string;
  token: string;
  slug?: string;
};

export type GoogleCalendarConnectionStatus = {
  provider: 'google_calendar' | string;
  auth_type?: string | null;
  status: string;
  connected: boolean;
  scopes: string[];
  metadata: { account_email?: string | null; [key: string]: unknown };
  expires_at?: string | null;
};

export type PlanFeature = { feature_key: string; enabled: boolean; limit_value: number | null; limit_unit: string | null };
export type BillingPlan = { code: string; name: string; description: string | null; monthly_price_cents: number | null; annual_price_cents: number | null; currency: string; features: PlanFeature[] };
export type Subscription = { status: string; provider: string; billing_interval: string | null; trial_started_at: string | null; trial_ends_at: string | null; current_period_end: string | null };
export type TrialBillingState = { status: string; days_remaining: number; trial_started_at: string | null; trial_ends_at: string | null; plan: string | null; expired: boolean };
export type EffectiveEntitlement = PlanFeature & { source: string };
export type CurrentBillingState = { tenant_id: string; plan: BillingPlan | null; subscription: Subscription | null; trial: boolean; days_remaining: number; expired: boolean; effective_entitlements: EffectiveEntitlement[]; enforcement_enabled: boolean; billing_ui_enabled: boolean; stripe_enabled?: boolean };


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
  status?: string;
  assignedUserId?: string | null;
  assignedUserName?: string | null;
  awaitingHumanAssignment?: boolean;
  inHumanCare?: boolean;
};

export type ChatMessage = {
  id: string;
  text: string;
  fromMe: boolean;
  time: string;
  createdAt?: string;
  status?: 'sent' | 'delivered' | 'read';
  mediaType?: 'image' | 'document' | string;
  mediaUrl?: string | null;
  attachmentUrl?: string | null;
  attachmentType?: string | null;
  fileUrl?: string | null;
  fileType?: string | null;
  caption?: string | null;
  filename?: string | null;
  isNew?: boolean;
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
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  tags_json?: string[];
  last_order_id?: string | null;
  city?: string | null;
  company?: string | null;
  plan?: string | null;
  lifecycle_stage?: string | null;
  notes?: string | null;
  source?: string;
  opt_in_status?: string;
  last_interaction_at?: string | null;
  custom_fields_json?: Record<string, any>;
  avatar_url?: string | null;
  stage: string;
  score: number;
  last_message_at?: string | null;
  last_message?: string | null;
  created_at: string;
  updated_at?: string;
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
  contact_name?: string | null;
  phone: string;
  last_message: string | null;
  temperature: PipelineTemperature;
  score: number;
  stage_id: string | null;
  last_interaction: string | null;
  entered_stage_at?: string | null;
  source?: string | null;
  status?: string | null;
  email?: string | null;
  responsible_user_id?: string | null;
  assigned_user_id?: string | null;
  owner_id?: string | null;
  assignee_id?: string | null;
  responsible_user_email?: string | null;
  assigned_user_email?: string | null;
  owner_email?: string | null;
  responsible_user_name?: string | null;
  assigned_user_name?: string | null;
  owner_name?: string | null;
};

export type PipelineStage = {
  id: string;
  name: string;
  position: number;
  is_final_stage?: boolean;
  leads: PipelineLead[];
};

export type PipelineStagePayload = {
  name?: string;
  position?: number;
};

export type WorkspaceProfile = 'private_sales' | 'government';


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
  seconds?: number;
  data: {
    label?: string;
    content?: string;
    seconds?: number;
    delay?: string | number;
    wait_seconds?: string | number;
    duration?: string | number;
    show_typing?: boolean;
    typing_duration_mode?: 'delay' | 'auto';
    body_text?: string;
    display_mode?: 'buttons' | 'list';
    displayMode?: 'buttons' | 'list';
    buttons?: FlowChoiceButton[];
    sections?: unknown[];
    condition?: string;
    action?: string;
    action_type?: 'create_lead' | 'add_tag' | 'notify_team' | 'transfer_human' | 'set_conversation_mode' | 'create_task' | 'send_cta_url';
    mode?: 'human' | 'bot' | 'ai';
    params?: Record<string, unknown>;
    tag?: string;
    message?: string;
    text?: string;
    button_text?: string;
    buttonText?: string;
    url?: string;
    href?: string;
    reason?: string;
    lead_name?: string;
    notification_title?: string;
    notification_message?: string;
    notification_priority?: 'low' | 'normal' | 'high';
    media_type?: 'image' | 'document' | 'audio' | 'video';
    media_url?: string;
    caption?: string;
    filename?: string;
    isStart?: boolean;
    metadata?: Record<string, unknown>;
    onChange?: (nodeId: string, patch: Record<string, unknown>) => void;
    is_terminal?: boolean;
    hasValidationError?: boolean;
    instruction?: string;
    input_template?: string;
    categories?: string[];
    allow_other?: boolean;
    confidence_threshold?: number;
    output_variable?: string;
    save_to_contact?: boolean;
    save_to_lead?: boolean;
    send_debug_message?: boolean;
    fields?: Array<{ name: string; type: 'string' | 'number' | 'boolean' | 'date' | 'email' | 'phone' | 'cpf' | 'cnpj'; description?: string }>;
    include_conversation_history?: boolean;
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
  status?: string;
  is_published?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  total_entries: number;
  total_completions: number;
  conversion_rate: number;
  last_execution_at?: string | null;
  published: boolean;
  draft: boolean;
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
  summary: { entries: number; conversions?: number; conversion_rate: number; abandonments?: number; abandonment_rate?: number; avg_duration_seconds?: number; messages_handled?: number; messages_sent: number; completed: number; dropoff_rate: number; avg_time_seconds: number; avg_messages_per_user?: number; };
  version?: { mode: string; active_flow_version_id?: string | null; selected_flow_version_id?: string | null; available_versions?: Array<{ id: string; label: string; display_version?: string; created_at?: string | null; is_active?: boolean }> };
  funnel: Array<{ node_id: string; node_label: string; node_type: string; entries?: number; entered?: number; exits?: number; completed?: number; conversions?: number; dropoff?: number; dropoffs?: number; dropoff_rate: number; conversion_to_next_rate?: number; avg_time_seconds?: number | null; }>;
  node_metrics?: Array<{ node_id: string; node_label: string; node_type: string; entered: number; completed: number; conversions: number; dropoff: number; dropoff_rate: number; avg_time_seconds?: number | null; }>;
  transition_metrics?: Array<{ source_node_id: string; target_node_id: string; source_handle?: string | null; count: number; rate_from_source: number }>;
  top_dropoffs: Array<{ node_id: string; node_label: string; node_type: string; entries: number; exits: number; dropoff_rate: number; conversion_to_next_rate: number; avg_time_seconds: number; }>;
  common_replies: Array<{ text?: string; reply?: string; count: number; rate?: number }>;
  timeline: Array<{ date: string; entries: number; messages_sent: number; completed: number }>;
  insights: Array<{ type: 'warning' | 'info' | 'success' | string; title: string; message: string; node_id?: string | null }>;
};

export type SystemSettings = {
  has_whatsapp_token: boolean;
  phone_number_id: string | null;
  system_name: string;
  language: string;
  workspace_profile: WorkspaceProfile;
};

export type SystemSettingsPayload = {
  token?: string | null;
  whatsapp_token?: string | null;
  phone_number_id?: string | null;
  webhook_url?: string | null;
  webhook_status?: string | null;
  system_name?: string;
  language?: string;
  workspace_profile?: WorkspaceProfile;
};

export type WhatsAppProvider = { id:string; provider_type:string; auth_type?: 'manual' | 'embedded_signup'; display_name?:string|null; waba_id?:string|null; phone_number_id?:string|null; business_id?:string|null; is_active:boolean; status:string; connection_status:'connected'|'token_expired'|'invalid_token'|'invalid_phone_number'|'meta_error'|'disconnected'|string; last_validation_at?: string | null; last_validation_error?: string | null; metadata_json?: Record<string, any>; last_connection_check_at?: string | null; updated_at?: string; access_token_masked?:string|null; connection_type?: 'cloud_api' | 'cloud_api_coexistence' | string; coexistence_enabled?: boolean; coexistence_status?: string | null; business_phone_number_id?: string | null; phone_display_name?: string | null; phone_verified_name?: string | null; onboarding_metadata?: Record<string, any> | null };
export type WhatsAppTemplate = { id:string; name:string; status:string; language:string; category?:string|null; provider_id?: string | null; body_text:string; body_raw_meta?: string; body_preview?: string | null; rejection_reason?: string | null; quality_score?: string | null; quality_rating?: string | null; components?: Array<Record<string, any>>; metadata_json?: Record<string, any> | string | null; variables_json?: Array<{ position:number; key:string; label:string; example:string }> | null; updated_at?: string | null };

export type WhatsAppCampaign = {
  id: string;
  name: string;
  status: string;
  provider_id: string;
  template_id: string;
  total_recipients: number;
  total_sent: number;
  total_delivered: number;
  total_read: number;
  total_failed: number;
  scheduled_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  metadata_json?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
};

export type WhatsAppCampaignRecipient = {
  id: string;
  campaign_id: string;
  phone: string;
  first_name?: string | null;
  status: string;
  provider_message_id?: string | null;
  error_message?: string | null;
  sent_at?: string | null;
  delivered_at?: string | null;
  read_at?: string | null;
  failed_at?: string | null;
};

export type TaskItem = {
  id: string;
  tenant_id: string;
  conversation_id?: string | null;
  contact_id?: string | null;
  lead_id?: string | null;
  title: string;
  description?: string | null;
  priority: string;
  status: string;
  assigned_to?: string | null;
  due_at?: string | null;
  completed_at?: string | null;
  completed_by?: string | null;
  created_at: string;
  updated_at: string;
  contact_name?: string | null;
  contact_phone?: string | null;
  conversation_name?: string | null;
  conversation_phone?: string | null;
};

export type TaskUpdatePayload = Partial<Pick<TaskItem, 'status' | 'assigned_to' | 'priority' | 'due_at' | 'title' | 'description'>>;
