"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";

import ChatWindow from "./ChatWindow";
import Sidebar from "./Sidebar";
import CRMContactSidebar from "./inbox/CRMContactSidebar";
import {
  getConversations,
  getMessagesByConversation,
  resetConversation,
  sendMessage,
  updateConversationMode,
} from "../lib/api";
import {
  ChatMessage,
  Contact,
  Conversation,
  ConversationMode,
  Message,
} from "../lib/types";
import { useRealtime } from "../hooks/useRealtime";
import { formatTimeBR } from "../lib/date";

type ConversationAssignmentSnapshot = {
  mode: string;
  assignedUserId: string | null;
};

type ConversationModeOverride = {
  mode: ConversationMode;
  updatedAt: number;
};

type ConversationModeUpdateResponse = {
  mode?: unknown;
  conversation?: {
    mode?: unknown;
  } | null;
};
type PresenceSnapshot = {
  status: "online" | "offline";
  lastSeen?: string | null;
  participantName?: string | null;
};

type TypingSnapshot = {
  participantName?: string | null;
  participantType?: string | null;
  expiresAt: number;
};

type RealtimeEvent = {
  type?: string;
  refresh?: string[];
  tenant_id?: string;
  conversation_id?: string;
  participant_id?: string;
  participant_type?: string;
  participant_name?: string | null;
  status?: string;
  last_seen?: string | null;
  is_typing?: boolean;
  message?: { conversation_id: string } | string | null;
  event?: string;
  action?: string;
  event_id?: string;
  id?: string;
  title?: string;
  priority?: string;
  activity?: {
    id?: string;
    type?: string;
    title?: string;
    description?: string;
    created_at?: string;
    entity_id?: string;
  };
};

const RECENT_MODE_OVERRIDE_TTL_MS = 30_000;
const TYPING_STOP_DELAY_MS = 2000;
const TYPING_START_THROTTLE_MS = 3000;
const TEAM_NOTIFICATION_TOAST_MS = 7000;
const TEAM_NOTIFICATION_DEDUPE_WINDOW_MS = 3000;

type TeamNotificationDetails = {
  id: string;
  conversationId: string;
  title: string;
  message: string;
  priority: string;
};

function normalizeRealtimeType(payload: RealtimeEvent) {
  return String(
    payload.event || payload.type || payload.action || "",
  ).toLowerCase();
}

function normalizePriorityLabel(priority: string) {
  const normalized = priority.toLowerCase();
  if (normalized === "high" || normalized === "alta") return "Alta";
  if (normalized === "low" || normalized === "baixa") return "Baixa";
  return "Normal";
}

function getTeamNotificationDetails(
  payload: RealtimeEvent,
): TeamNotificationDetails {
  const rawMessage = typeof payload.message === "string" ? payload.message : "";
  const title =
    String(
      payload.title || payload.activity?.title || "Equipe notificada",
    ).trim() || "Equipe notificada";
  const message = String(
    rawMessage || payload.activity?.description || "",
  ).trim();
  const priority = String(payload.priority || "normal").toLowerCase();
  const conversationId = String(
    payload.conversation_id || payload.activity?.entity_id || "",
  );
  const id = String(
    payload.event_id ||
      payload.activity?.id ||
      payload.id ||
      [conversationId, title, message, priority].join("|"),
  );

  return { id, conversationId, title, message, priority };
}

function normalizeConversationMode(value: unknown): ConversationMode | null {
  if (typeof value !== "string") return null;

  const normalizedMode = value.toLowerCase();
  if (
    normalizedMode === "human" ||
    normalizedMode === "bot" ||
    normalizedMode === "ai"
  ) {
    return normalizedMode;
  }

  return null;
}

function getAssignedUserName(conversation: Conversation) {
  return conversation.assigned_user_name?.trim() || "Atendente";
}

function getConversationModeErrorMessage(error: unknown) {
  const fallback = "Não foi possível atualizar o modo.";
  if (!(error instanceof Error)) return fallback;

  const match = error.message.match(/^HTTP\s+\d+:\s*([\s\S]*)$/);
  const rawBody = match?.[1]?.trim();
  if (!rawBody) return fallback;

  try {
    const parsed = JSON.parse(rawBody) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail.trim();
    }
  } catch {
    return rawBody;
  }

  return fallback;
}

function formatPresenceStatus(snapshot?: PresenceSnapshot) {
  if (!snapshot) return "Ativo recentemente";
  if (snapshot.status === "online") return "Online";

  if (snapshot.lastSeen) {
    const date = new Date(snapshot.lastSeen);
    if (!Number.isNaN(date.getTime())) {
      return `Visto por último às ${date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
    }
  }

  return "Ativo recentemente";
}

function formatTypingText(snapshot?: TypingSnapshot) {
  if (!snapshot || snapshot.expiresAt <= Date.now()) return "";

  if (snapshot.participantType === "contact")
    return "Cliente está digitando...";
  const name = snapshot.participantName?.trim() || "Atendente";
  return `${name} está digitando...`;
}

function toChatMessage(message: Message): ChatMessage {
  const parsedDate = new Date(
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(message.created_at)
      ? `${message.created_at}Z`
      : message.created_at,
  );
  const time = Number.isNaN(parsedDate.getTime())
    ? "--:--"
    : formatTimeBR(message.created_at);

  return {
    id: String(message.id),
    text: message.content,
    fromMe: message.role === "assistant",
    time,
    createdAt: message.created_at,
    status: message.role === "assistant" ? "read" : "delivered",
    isNew: Date.now() - parsedDate.getTime() < 8000,
  };
}

export default function ChatShell() {
  console.log("[COMPONENT RENDER] ChatShell");
  const router = useRouter();
  const searchParams = useSearchParams();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedContactId, setSelectedContactId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mode, setMode] = useState<ConversationMode>("human");
  const [modeUpdating, setModeUpdating] = useState(false);
  const [modeNotice, setModeNotice] = useState("");
  const [modeError, setModeError] = useState("");
  const [querySelectionMissing, setQuerySelectionMissing] = useState(false);
  const [crmOpen, setCrmOpen] = useState(false);
  const [handoffToast, setHandoffToast] = useState("");
  const [resetToast, setResetToast] = useState("");
  const [teamNotificationToast, setTeamNotificationToast] =
    useState<TeamNotificationDetails | null>(null);
  const [resetError, setResetError] = useState("");
  const [resettingConversation, setResettingConversation] = useState(false);
  const [presenceByConversation, setPresenceByConversation] = useState<
    Record<string, PresenceSnapshot>
  >({});
  const [typingByConversation, setTypingByConversation] = useState<
    Record<string, TypingSnapshot>
  >({});
  const previousAssignmentRef = useRef<
    Map<string, ConversationAssignmentSnapshot>
  >(new Map());
  const recentModeOverridesRef = useRef<Map<string, ConversationModeOverride>>(
    new Map(),
  );
  const hasLoadedConversationsRef = useRef(false);
  const typingStopTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const lastTypingStartRef = useRef(0);
  const teamNotificationDedupeRef = useRef<Map<string, number>>(new Map());
  const [crmRefreshKey, setCrmRefreshKey] = useState(0);

  const playHumanHandoffSound = useCallback(() => {
    // TODO: Reativar notificação sonora quando houver um asset de áudio existente/aprovado no projeto.
  }, []);

  const applyConversations = useCallback(
    (items: Conversation[], options: { notifyHandoff?: boolean } = {}) => {
      console.log("[APPLY CONVERSATIONS]", items.length);
      const notifyHandoff = options.notifyHandoff ?? true;
      const previousAssignments = previousAssignmentRef.current;
      const recentModeOverrides = recentModeOverridesRef.current;
      const now = Date.now();
      const normalizedItems = items.map((conversation) => {
        const conversationId = String(conversation.id);
        const override = recentModeOverrides.get(conversationId);

        if (!override) return conversation;

        if (now - override.updatedAt > RECENT_MODE_OVERRIDE_TTL_MS) {
          recentModeOverrides.delete(conversationId);
          return conversation;
        }

        return { ...conversation, mode: override.mode };
      });

      if (notifyHandoff && hasLoadedConversationsRef.current) {
        const assignedConversation = normalizedItems.find((conversation) => {
          const previous = previousAssignments.get(String(conversation.id));
          const currentMode = String(conversation.mode || "").toLowerCase();
          const currentAssignedUserId = conversation.assigned_user_id
            ? String(conversation.assigned_user_id)
            : null;

          return Boolean(
            previous &&
            previous.mode === "human" &&
            !previous.assignedUserId &&
            currentMode === "human" &&
            currentAssignedUserId,
          );
        });

        if (assignedConversation) {
          setHandoffToast(
            `${getAssignedUserName(assignedConversation)} assumiu o atendimento`,
          );
        } else {
          const handoffConversation = normalizedItems.find((conversation) => {
            const previous = previousAssignments.get(String(conversation.id));
            const currentMode = String(conversation.mode || "").toLowerCase();

            return Boolean(
              previous && previous.mode !== "human" && currentMode === "human",
            );
          });

          if (handoffConversation) {
            const displayName =
              handoffConversation.name ||
              handoffConversation.phone ||
              "Conversa";
            setHandoffToast(
              `Cliente solicitou atendimento humano: ${displayName}`,
            );
            playHumanHandoffSound();
          }
        }
      }

      previousAssignmentRef.current = new Map(
        normalizedItems.map((conversation) => [
          String(conversation.id),
          {
            mode: String(conversation.mode || "").toLowerCase(),
            assignedUserId: conversation.assigned_user_id
              ? String(conversation.assigned_user_id)
              : null,
          },
        ]),
      );
      hasLoadedConversationsRef.current = true;
      console.log("[SET CONVERSATIONS]", items.length);
      setConversations(normalizedItems);
    },
    [playHumanHandoffSound],
  );

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.replace("/login");
    }
  }, [router]);

  const fetchMessages = useCallback(
    async (conversationId: string) => {
      const conversation = conversations.find(
        (item) => String(item.contact_id ?? item.id) === conversationId,
      );

      if (!conversation) {
        setMessages([]);
        return;
      }

      const realMessages: Message[] = await getMessagesByConversation(
        String(conversation.id),
      );
      setMessages(realMessages.map(toChatMessage));
    },
    [conversations],
  );

  const contacts = useMemo<Contact[]>(() => {
    console.log("[CONTACTS MEMO]", conversations.length);
    return conversations.map((conversation) => {
      return {
        id: String(conversation.contact_id ?? conversation.id),
        name: conversation.name,
        phone: conversation.phone,
        avatarUrl: conversation.avatar_url,
        stage: conversation.stage,
        score: conversation.score,
        lastMessage: conversation.last_message,
        lastMessageAt: conversation.updated_at,
        status: conversation.mode,
        assignedUserId: conversation.assigned_user_id ?? null,
        assignedUserName: conversation.assigned_user_name ?? null,
        awaitingHumanAssignment:
          String(conversation.mode || "").toLowerCase() === "human" &&
          !conversation.assigned_user_id,
        inHumanCare:
          String(conversation.mode || "").toLowerCase() === "human" &&
          Boolean(conversation.assigned_user_id),
      };
    });
  }, [conversations]);

  const orderedContacts = useMemo(() => {
    const getPriority = (status?: string) => {
      const normalizedStatus = status?.toLowerCase();

      if (normalizedStatus === "human") return 2;
      if (normalizedStatus === "bot" || normalizedStatus === "ai") return 1;
      return 0;
    };

    return [...contacts].sort((a, b) => {
      const priorityDiff = getPriority(a.status) - getPriority(b.status);
      if (priorityDiff !== 0) return priorityDiff;

      const dateA = a.lastMessageAt ? new Date(a.lastMessageAt).getTime() : 0;
      const dateB = b.lastMessageAt ? new Date(b.lastMessageAt).getTime() : 0;
      return dateB - dateA;
    });
  }, [contacts]);

  const unansweredCount = useMemo(
    () =>
      orderedContacts.filter((contact) => {
        const normalizedStatus = contact.status?.toLowerCase();
        return (
          normalizedStatus !== "human" &&
          normalizedStatus !== "bot" &&
          normalizedStatus !== "ai"
        );
      }).length,
    [orderedContacts],
  );

  const humanRequestsCount = useMemo(
    () =>
      conversations.filter(
        (conversation) =>
          String(conversation.mode || "").toLowerCase() === "human" &&
          !conversation.assigned_user_id,
      ).length,
    [conversations],
  );

  const selectedContact = useMemo(
    () => contacts.find((contact) => contact.id === selectedContactId),
    [contacts, selectedContactId],
  );
  const selectedConversation = useMemo(
    () =>
      conversations.find(
        (item) => String(item.contact_id ?? item.id) === selectedContactId,
      ),
    [conversations, selectedContactId],
  );

  useEffect(() => {
    if (!selectedConversation) {
      return;
    }

    const currentMode = selectedConversation.mode?.toLowerCase();
    if (
      currentMode === "bot" ||
      currentMode === "ai" ||
      currentMode === "human"
    ) {
      setMode(currentMode);
      return;
    }
  }, [selectedConversation]);

  useEffect(() => {
    if (!modeNotice && !modeError) return;

    const timeoutId = window.setTimeout(() => {
      setModeNotice("");
      setModeError("");
    }, 2200);

    return () => window.clearTimeout(timeoutId);
  }, [modeNotice, modeError]);

  useEffect(() => {
    if (!handoffToast) return;

    const timeoutId = window.setTimeout(() => setHandoffToast(""), 5000);

    return () => window.clearTimeout(timeoutId);
  }, [handoffToast]);

  useEffect(() => {
    if (!teamNotificationToast) return;

    const timeoutId = window.setTimeout(
      () => setTeamNotificationToast(null),
      TEAM_NOTIFICATION_TOAST_MS,
    );

    return () => window.clearTimeout(timeoutId);
  }, [teamNotificationToast]);

  useEffect(() => {
    if (!resetToast && !resetError) return;

    const timeoutId = window.setTimeout(() => {
      setResetToast("");
      setResetError("");
    }, 4000);

    return () => window.clearTimeout(timeoutId);
  }, [resetToast, resetError]);

  const showTeamNotification = useCallback(
    (payload: RealtimeEvent) => {
      if (
        normalizeRealtimeType(payload) !== "team_notification" &&
        payload.action !== "TEAM_NOTIFICATION_CREATED"
      )
        return false;

      console.log("[TEAM_NOTIFICATION EVENT]", payload);
      const details = getTeamNotificationDetails(payload);
      const dedupeKey = payload.event_id || details.id;
      const now = Date.now();
      const lastSeen = teamNotificationDedupeRef.current.get(dedupeKey);
      if (lastSeen && now - lastSeen < TEAM_NOTIFICATION_DEDUPE_WINDOW_MS) {
        return true;
      }

      teamNotificationDedupeRef.current.set(dedupeKey, now);
      teamNotificationDedupeRef.current.forEach((timestamp, key) => {
        if (now - timestamp > TEAM_NOTIFICATION_DEDUPE_WINDOW_MS) {
          teamNotificationDedupeRef.current.delete(key);
        }
      });

      setTeamNotificationToast(details);
      setCrmRefreshKey((current) => current + 1);

      if (
        details.conversationId &&
        selectedConversation &&
        details.conversationId === String(selectedConversation.id)
      ) {
        fetchMessages(
          String(selectedConversation.contact_id ?? selectedConversation.id),
        ).catch(() => undefined);
      }

      return true;
    },
    [fetchMessages, selectedConversation],
  );

  // A lógica de tempo real está centralizada nos hooks useRealtime abaixo

  useEffect(() => {
    console.log("[FRONTEND SELECTED CONVERSATION]", selectedConversation?.id);
  }, [selectedConversation]);

  useRealtime({
    wsUrl: `${process.env.NEXT_PUBLIC_API_URL?.replace(/^https/, "wss").replace(/^http/, "ws")}/api/dashboard/ws`,
    sseUrl: `${process.env.NEXT_PUBLIC_API_URL}/api/dashboard/stream`,
    tenantId:
      typeof window !== "undefined"
        ? localStorage.getItem("tenant_id") || ""
        : "",
    onMessage: (payload: RealtimeEvent) => {
      console.log("[WS MESSAGE]", payload);
      if (
        payload?.type === "presence_updated" &&
        payload.conversation_id &&
        (payload.status === "online" || payload.status === "offline")
      ) {
        setPresenceByConversation((current) => ({
          ...current,
          [String(payload.conversation_id)]: {
            status: payload.status as "online" | "offline",
            lastSeen: payload.last_seen ?? null,
            participantName: payload.participant_name ?? null,
          },
        }));
        return;
      }
      showTeamNotification(payload);
      if (!payload?.refresh?.includes("conversations")) return;
      getConversations()
        .then((items) => {
          console.log("[API RESULT]", items);
          applyConversations(items);
        })
        .catch(() => undefined);
    },
  });

  const messageWsUrl = selectedConversation
    ? `${process.env.NEXT_PUBLIC_API_URL?.replace(/^https/, "wss").replace(/^http/, "ws")}/api/ws/messages/${selectedConversation.id}`
    : "";
  const messageSseUrl = selectedConversation
    ? `${process.env.NEXT_PUBLIC_API_URL}/api/sse/messages/${selectedConversation.id}`
    : "";

  console.log("[BEFORE MESSAGE HOOK]", selectedConversation?.id);
  console.log("[MESSAGE WS URL]", messageWsUrl);

  const {
    connected: messageRealtimeConnected,
    sendJson: sendMessageRealtimeJson,
  } = useRealtime({
    wsUrl: messageWsUrl,
    sseUrl: messageSseUrl,
    tenantId:
      typeof window !== "undefined"
        ? localStorage.getItem("tenant_id") || ""
        : "",
    onMessage: (payload: RealtimeEvent) => {
      console.log(
        "[WS MESSAGE RECEIVED CONVERSATION]",
        typeof payload?.message === "object"
          ? payload?.message?.conversation_id
          : payload?.conversation_id || payload?.type,
      );
      if (
        payload?.type === "presence_updated" &&
        payload.conversation_id &&
        (payload.status === "online" || payload.status === "offline")
      ) {
        setPresenceByConversation((current) => ({
          ...current,
          [String(payload.conversation_id)]: {
            status: payload.status as "online" | "offline",
            lastSeen: payload.last_seen ?? null,
            participantName: payload.participant_name ?? null,
          },
        }));
        return;
      }

      if (payload?.type === "typing" && payload.conversation_id) {
        const conversationId = String(payload.conversation_id);
        setTypingByConversation((current) => {
          const next = { ...current };
          if (payload.is_typing) {
            next[conversationId] = {
              participantName: payload.participant_name ?? null,
              participantType: payload.participant_type ?? null,
              expiresAt: Date.now() + 5500,
            };
          } else {
            delete next[conversationId];
          }
          return next;
        });
        return;
      }

      showTeamNotification(payload);
      if (!selectedContactId) return;
      fetchMessages(selectedContactId).catch(() => undefined);
      getConversations()
        .then((items) => applyConversations(items))
        .catch(() => undefined);
    },
  });

  useEffect(() => {
    if (!selectedConversation || !messageRealtimeConnected) return;

    sendMessageRealtimeJson({ type: "presence_heartbeat" });
    const intervalId = window.setInterval(() => {
      sendMessageRealtimeJson({ type: "presence_heartbeat" });
    }, 20_000);

    return () => window.clearInterval(intervalId);
  }, [messageRealtimeConnected, selectedConversation, sendMessageRealtimeJson]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      const now = Date.now();
      setTypingByConversation((current) => {
        let changed = false;
        const next = { ...current };
        Object.entries(next).forEach(([conversationId, snapshot]) => {
          if (snapshot.expiresAt <= now) {
            delete next[conversationId];
            changed = true;
          }
        });
        return changed ? next : current;
      });
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    return () => {
      if (typingStopTimeoutRef.current)
        clearTimeout(typingStopTimeoutRef.current);
      sendMessageRealtimeJson({ type: "typing_stop" });
    };
  }, [selectedConversation?.id, sendMessageRealtimeJson]);

  const emitTypingActivity = useCallback(
    (value: string) => {
      if (!selectedConversation) return;

      if (!value.trim()) {
        if (typingStopTimeoutRef.current)
          clearTimeout(typingStopTimeoutRef.current);
        typingStopTimeoutRef.current = null;
        lastTypingStartRef.current = 0;
        sendMessageRealtimeJson({ type: "typing_stop" });
        return;
      }

      const now = Date.now();
      if (now - lastTypingStartRef.current > TYPING_START_THROTTLE_MS) {
        sendMessageRealtimeJson({ type: "typing_start" });
        lastTypingStartRef.current = now;
      }

      if (typingStopTimeoutRef.current)
        clearTimeout(typingStopTimeoutRef.current);
      typingStopTimeoutRef.current = setTimeout(() => {
        sendMessageRealtimeJson({ type: "typing_stop" });
        lastTypingStartRef.current = 0;
        typingStopTimeoutRef.current = null;
      }, TYPING_STOP_DELAY_MS);
    },
    [selectedConversation, sendMessageRealtimeJson],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      setInputValue(value);
      emitTypingActivity(value);
    },
    [emitTypingActivity],
  );

  useEffect(() => {
    getConversations()
      .then((items) => {
        const targetContactId = searchParams.get("contact_id");
        const targetPhone = searchParams.get("phone");
        const normalizedTargetPhone = targetPhone
          ? targetPhone.replace(/\D/g, "")
          : "";

        applyConversations(items, { notifyHandoff: false });

        const matchedConversation = items.find((conversation) => {
          const byContactId = targetContactId
            ? String(conversation.contact_id ?? conversation.id) ===
              targetContactId
            : false;

          const byPhone = normalizedTargetPhone
            ? conversation.phone.replace(/\D/g, "") === normalizedTargetPhone
            : false;

          return byContactId || byPhone;
        });

        if (matchedConversation) {
          setQuerySelectionMissing(false);
          setSelectedContactId(
            String(matchedConversation.contact_id ?? matchedConversation.id),
          );
          return;
        }

        if (targetContactId || targetPhone) {
          setQuerySelectionMissing(true);
        }

        setSelectedContactId(
          (current) =>
            current ||
            (items[0] ? String(items[0].contact_id ?? items[0].id) : ""),
        );
      })
      .catch(() => setConversations([]));
  }, [searchParams, applyConversations]);

  function onSelectContact(contactId: string) {
    setSelectedContactId(contactId);
    setCrmOpen(true);
  }

  async function onSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedContact || !inputValue.trim()) return;

    const text = inputValue.trim();
    const now = new Date();
    const newMessage: ChatMessage = {
      id: `${now.getTime()}`,
      text,
      fromMe: true,
      time: now.toLocaleTimeString("pt-BR", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    };

    setMessages((current) => [...current, newMessage]);
    setInputValue("");
    if (typingStopTimeoutRef.current)
      clearTimeout(typingStopTimeoutRef.current);
    typingStopTimeoutRef.current = null;
    lastTypingStartRef.current = 0;
    sendMessageRealtimeJson({ type: "typing_stop" });

    try {
      await sendMessage(selectedContact.phone, text, selectedContact.id);
    } catch (error) {
      console.error("Falha ao enviar para backend:", error);
    }
  }

  async function handleResetConversation() {
    if (!selectedConversation || resettingConversation) return;

    setResetToast("");
    setResetError("");
    setResettingConversation(true);

    try {
      await resetConversation(String(selectedConversation.id));
      const refreshedConversations = await getConversations();
      applyConversations(refreshedConversations, { notifyHandoff: false });
      setMessages([]);
      setSelectedContactId(
        refreshedConversations[0]
          ? String(
              refreshedConversations[0].contact_id ??
                refreshedConversations[0].id,
            )
          : "",
      );
      setResetToast("Conversa resetada com sucesso.");
    } catch (err) {
      console.error("Erro ao resetar conversa:", err);
      setResetError("Não foi possível resetar a conversa.");
    } finally {
      setResettingConversation(false);
    }
  }

  async function handleChangeMode(newMode: ConversationMode) {
    if (!selectedConversation || modeUpdating || newMode === mode) return;

    const conversationId = String(selectedConversation.id);
    const previousMode = mode;

    setModeError("");
    setModeNotice("");
    setModeUpdating(true);

    try {
      const response = (await updateConversationMode(
        conversationId,
        newMode,
      )) as ConversationModeUpdateResponse | null | undefined;
      const updatedMode =
        normalizeConversationMode(response?.conversation?.mode) ??
        normalizeConversationMode(response?.mode) ??
        newMode;

      recentModeOverridesRef.current.set(conversationId, {
        mode: updatedMode,
        updatedAt: Date.now(),
      });
      setMode(updatedMode);
      const updatedConversations = conversations.map((conversation) =>
        String(conversation.id) === conversationId
          ? { ...conversation, mode: updatedMode }
          : conversation,
      );
      applyConversations(updatedConversations, { notifyHandoff: false });
      setModeNotice("Modo atualizado.");
    } catch (err) {
      console.error("Erro ao atualizar modo:", err);
      setMode(previousMode);
      setModeError(getConversationModeErrorMessage(err));
    } finally {
      setModeUpdating(false);
    }
  }

  return (
    <div className="wa-layout">
      <Sidebar
        contacts={orderedContacts}
        selectedContactId={selectedContactId}
        onSelectContact={onSelectContact}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
        unansweredCount={unansweredCount}
        humanRequestsCount={humanRequestsCount}
      />
      <ChatWindow
        contact={selectedContact}
        messages={messages}
        inputValue={inputValue}
        onInputChange={handleInputChange}
        onSend={onSend}
        onToggleSidebar={() => setSidebarOpen((value) => !value)}
        mode={mode}
        presenceStatus={formatPresenceStatus(
          selectedConversation
            ? presenceByConversation[String(selectedConversation.id)]
            : undefined,
        )}
        typingText={formatTypingText(
          selectedConversation
            ? typingByConversation[String(selectedConversation.id)]
            : undefined,
        )}
        modeUpdating={modeUpdating}
        modeNotice={modeNotice}
        modeError={modeError}
        emptyStateMessage={
          querySelectionMissing
            ? "Conversa ainda não encontrada para este contato."
            : undefined
        }
        resetInProgress={resettingConversation}
        onResetConversation={
          selectedConversation ? handleResetConversation : undefined
        }
        onModeChange={handleChangeMode}
      />
      {handoffToast ? (
        <div className="wa-handoff-toast" role="status">
          {handoffToast}
        </div>
      ) : null}
      {teamNotificationToast ? (
        <div
          className={`wa-team-notification-toast priority-${teamNotificationToast.priority}`}
          role="status"
        >
          <div className="wa-team-notification-icon" aria-hidden="true">
            🔔
          </div>
          <div>
            <strong>Equipe notificada</strong>
            <p className="wa-team-notification-title">
              {teamNotificationToast.title}
            </p>
            {teamNotificationToast.message ? (
              <p>{teamNotificationToast.message}</p>
            ) : null}
            <span>
              Prioridade:{" "}
              {normalizePriorityLabel(teamNotificationToast.priority)}
            </span>
          </div>
        </div>
      ) : null}
      {resetToast ? (
        <div className="wa-reset-toast success" role="status">
          {resetToast}
        </div>
      ) : null}
      {resetError ? (
        <div className="wa-reset-toast error" role="alert">
          {resetError}
        </div>
      ) : null}
      <CRMContactSidebar
        contact={selectedContact}
        conversationId={selectedConversation?.id}
        refreshKey={crmRefreshKey}
        open={crmOpen}
        onClose={() => setCrmOpen(false)}
      />
    </div>
  );
}
