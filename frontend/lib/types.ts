export type Conversation = {
  id: number;
  phone: string;
  name: string;
  last_message: string;
  assigned_to: 'IA' | 'HUMANO' | string;
};

export type Message = {
  id: number;
  phone: string;
  content: string;
  from_me: boolean;
  timestamp: string;
};
