import type { Contact, Conversation } from './types';

export type ConversationFilterId = 'all' | 'unanswered' | 'human' | 'bot' | 'ai' | 'awaiting';

export const CONVERSATION_FILTERS: ReadonlyArray<{ id: ConversationFilterId; label: string }> = [
  { id: 'all', label: 'Todos' },
  { id: 'unanswered', label: 'Não respondidas' },
  { id: 'human', label: 'Humano' },
  { id: 'bot', label: 'Bot' },
  { id: 'ai', label: 'IA' },
  { id: 'awaiting', label: 'Aguardando' },
];

type FilterableConversation = Pick<Conversation, 'mode' | 'assigned_user_id'>;
type FilterableContact = Pick<Contact, 'status' | 'assignedUserId' | 'awaitingHumanAssignment'>;

export function normalizeConversationStatus(value?: string | null) {
  return (value || '').trim().toLowerCase();
}

export function isUnansweredStatus(status?: string | null) {
  const normalized = normalizeConversationStatus(status);
  return normalized !== 'human' && normalized !== 'bot' && normalized !== 'ai';
}

export function isAwaitingHumanAssignment(item: FilterableConversation | FilterableContact) {
  if ('awaitingHumanAssignment' in item && typeof item.awaitingHumanAssignment === 'boolean') {
    return item.awaitingHumanAssignment;
  }

  if ('mode' in item) {
    return normalizeConversationStatus(item.mode) === 'human' && !item.assigned_user_id;
  }

  return normalizeConversationStatus(item.status) === 'human' && !item.assignedUserId;
}

export function matchesConversationFilter(
  item: FilterableConversation | FilterableContact,
  filter: ConversationFilterId,
) {
  const status = normalizeConversationStatus('mode' in item ? item.mode : item.status);

  if (filter === 'all') return true;
  if (filter === 'unanswered') return isUnansweredStatus(status);
  if (filter === 'awaiting') return isAwaitingHumanAssignment(item);
  return status === filter;
}
