export type Conversation = {
  id: string;
  tenant_id: string;
  contact_id?: string | null;
  phone: string;
  name: string | null;
  avatar_url?: string | null;
  stage?: string;
  score?: number;
  status: 'bot' | 'human' | string;
  last_message: string;
  updated_at: string;
};

export type Message = {
  id: string;
  tenant_id: string;
  phone: string;
  content: string;
  from_me: boolean;
  timestamp: string;
};

export type TenantSession = {
  tenant_id: string;
  slug: string;
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
  created_at: string;
};
