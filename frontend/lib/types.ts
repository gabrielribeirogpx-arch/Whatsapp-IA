export type Conversation = {
  id: number;
  tenant_id: number;
  phone: string;
  name: string;
  status: 'bot' | 'human' | string;
  last_message: string;
  updated_at: string;
};

export type Message = {
  id: number;
  tenant_id: number;
  phone: string;
  content: string;
  from_me: boolean;
  timestamp: string;
};

export type TenantAuth = {
  slug: string;
  password: string;
};

export type TenantSession = {
  tenant_id: number;
  name: string;
  slug: string;
  usage: {
    plan: string;
    is_blocked: boolean;
    max_monthly_messages: number;
    messages_used_month: number;
    usage_month: string;
  };
};

export type Contact = {
  id: string;
  name: string;
  phone: string;
  lastMessage: string;
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
