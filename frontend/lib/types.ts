export type Conversation = {
  id: number;
  phone: string;
  name: string;
  status: 'bot' | 'human' | string;
  last_message: string;
  updated_at: string;
};

export type Message = {
  id: number;
  phone: string;
  content: string;
  from_me: boolean;
  timestamp: string;
};
