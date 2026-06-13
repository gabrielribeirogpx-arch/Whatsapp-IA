"use client";

/**
 * MobileChatShell.tsx — v3 (Wazza Light Mode + Auth Guard)
 *
 * Mudanças vs v2:
 * - ✅ Auth guard: redireciona para /login se não há sessão
 * - ✅ Exibe MobileLoginScreen antes do inbox quando sem sessão
 * - ✅ Identidade visual Wazza (sem dark mode, sem violet/purple)
 * - ✅ SSE, Push, PWA — inalterados
 */

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  assignConversationToSelf,
  getAccountMe,
  getConversations,
  getMessagesByConversation,
  releaseConversationAssignment,
  sendMessage,
  updateConversationMode,
} from "@/lib/api";
import { formatTimeBR } from "@/lib/date";
import {
  ChatMessage,
  Contact,
  Conversation,
  ConversationMode,
  Message,
} from "@/lib/types";
import { usePushNotifications } from "@/hooks/mobile/usePushNotifications";
import { useServiceWorker } from "@/hooks/mobile/useServiceWorker";
import { usePWAInstall } from "@/hooks/mobile/usePWAInstall";
import { useRealtime } from "@/hooks/useRealtime";

import MobileConvoList from "./views/MobileConvoList";
import MobileChatView from "./views/MobileChatView";
import MobileNotifView, {
  addLocalNotif,
  getLocalNotifCount,
} from "./views/MobileNotifView";
import MobileProfileView from "./views/MobileProfileView";
import BottomNav from "./components/BottomNav";
import PushBanner from "./components/PushBanner";
import PushPermissionSheet from "./components/PushPermissionSheet";
import InstallPrompt from "./components/InstallPrompt";
import MobileLoginScreen from "./components/MobileLoginScreen";

export type MobileView = "inbox" | "chat" | "notifs" | "profile";

const MOBILE_INBOX_CACHE_KEY = "wazza-mobile-inbox-cache-v1";
const TEAM_NOTIFICATION_DEDUPE_WINDOW_MS = 3000;

type MobileRealtimePayload = Record<string, unknown> & {
  event?: string;
  type?: string;
  action?: string;
  event_id?: string;
  conversation_id?: string;
  title?: string;
  message?: string;
  priority?: string;
  activity?: {
    id?: string;
    title?: string;
    description?: string;
    entity_id?: string;
  };
};

// ─── Helpers ──────────────────────────────────────────────────

function isAuthenticated(): boolean {
  if (typeof window === "undefined") return false;
  const token = localStorage.getItem("token");
  return !!token && token.length > 0;
}

function readCachedConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(MOBILE_INBOX_CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { conversations?: Conversation[] };
    return Array.isArray(parsed.conversations) ? parsed.conversations : [];
  } catch {
    return [];
  }
}

function writeCachedConversations(conversations: Conversation[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      MOBILE_INBOX_CACHE_KEY,
      JSON.stringify({
        cachedAt: new Date().toISOString(),
        conversations,
      }),
    );
  } catch {
    /* best-effort */
  }
}

function updateAppBadge(count: number) {
  if (typeof navigator === "undefined") return;
  const nav = navigator as Navigator & {
    setAppBadge?: (contents?: number) => Promise<void>;
    clearAppBadge?: () => Promise<void>;
  };
  if (count > 0 && nav.setAppBadge) {
    nav.setAppBadge(count).catch(() => undefined);
  } else if (count === 0 && nav.clearAppBadge) {
    nav.clearAppBadge().catch(() => undefined);
  }
}

function normalizeRealtimeType(payload: MobileRealtimePayload) {
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

function getTeamNotificationDetails(payload: MobileRealtimePayload) {
  const title =
    String(
      payload.title || payload.activity?.title || "Equipe notificada",
    ).trim() || "Equipe notificada";
  const message = String(
    payload.message || payload.activity?.description || "",
  ).trim();
  const priority = String(payload.priority || "normal").toLowerCase();
  const conversationId = String(
    payload.conversation_id || payload.activity?.entity_id || "",
  );
  const id = String(
    payload.event_id ||
      payload.activity?.id ||
      [conversationId, title, message, priority].join("|"),
  );

  return { id, conversationId, title, message, priority };
}

function vibrate(pattern: VibratePattern) {
  if (typeof navigator !== "undefined" && "vibrate" in navigator) {
    navigator.vibrate(pattern);
  }
}

function toChatMessage(msg: Message): ChatMessage {
  const d = new Date(
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:.\d+)?$/.test(msg.created_at)
      ? `${msg.created_at}Z`
      : msg.created_at,
  );
  return {
    id: String(msg.id),
    text: msg.content,
    fromMe: msg.role === "assistant",
    time: isNaN(d.getTime()) ? "--:--" : formatTimeBR(msg.created_at),
    createdAt: msg.created_at,
    status: msg.role === "assistant" ? "read" : "delivered",
    isNew: Date.now() - d.getTime() < 5000,
  };
}

// ─── Main Component ───────────────────────────────────────────

export default function MobileChatShell() {
  console.log("[COMPONENT RENDER] MobileChatShell");
  // ── Auth state ───────────────────────────────────────────────
  const [authChecked, setAuthChecked] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    // Verifica sessão no client-side (após hidratação)
    setAuthed(isAuthenticated());
    setAuthChecked(true);
  }, []);

  // ── Inbox state ──────────────────────────────────────────────
  const [view, setView] = useState<MobileView>("inbox");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedConvoId, setSelectedConvoId] = useState<string | null>(null);
  const selectedConvoIdRef = useRef<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [filter, setFilter] = useState<"all" | "human" | "bot" | "pending">(
    "all",
  );
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<ConversationMode>("human");
  const [modeUpdating, setModeUpdating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pushBanner, setPushBanner] = useState<{
    title: string;
    text: string;
  } | null>(null);
  const [showPermSheet, setShowPermSheet] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [notifCount, setNotifCount] = useState(0);
  const teamNotificationDedupeRef = useRef<Map<string, number>>(new Map());

  // ── Hooks ────────────────────────────────────────────────────
  const {
    granted: pushGranted,
    requestPermission,
    subscribe,
  } = usePushNotifications();
  const { isInstallable, promptInstall } = usePWAInstall();
  useServiceWorker("/sw.js");

  // ── Derived ─────────────────────────────────────────────────
  const contacts = useMemo<Contact[]>(() => {
    console.log("[CONTACTS RECALCULATED]", conversations.length);
    return conversations.map((c) => ({
      id: String(c.contact_id ?? c.id),
      name: c.name,
      phone: c.phone,
      avatarUrl: c.avatar_url,
      stage: c.stage,
      score: c.score,
      lastMessage: c.last_message,
      lastMessageAt: c.updated_at,
      status: c.mode,
    }));
  }, [conversations]);

  const selectedConvo = useMemo(
    () => conversations.find((c) => c.id === selectedConvoId),
    [conversations, selectedConvoId],
  );
  const selectedContact = useMemo(
    () =>
      contacts.find(
        (c) => c.id === String(selectedConvo?.contact_id ?? selectedConvo?.id),
      ),
    [contacts, selectedConvo],
  );

  const pendingCount = useMemo(
    () =>
      contacts.filter(
        (c) => !["human", "bot", "ai"].includes((c.status || "").toLowerCase()),
      ).length,
    [contacts],
  );

  const assignedUserName = useMemo(() => {
    if (!selectedConvo?.assigned_user_id) return null;
    if (
      currentUserId &&
      String(selectedConvo.assigned_user_id) === currentUserId
    )
      return "Você";
    return selectedConvo.assigned_user_name || "Atendente";
  }, [currentUserId, selectedConvo]);

  const isAdmin = useMemo(() => {
    if (typeof window === "undefined") return false;
    return (window as any).__WAZZA_USER__?.role === "admin";
  }, []);

  // ── Fetch (apenas quando autenticado) ───────────────────────
  const fetchConversations = useCallback(async () => {
    try {
      const data = await getConversations();
      console.log("[AFTER API]", data.length);
      console.log("[FIRST CONVERSATION]", {
        id: data[0]?.id,
        last_message: data[0]?.last_message,
        updated_at: data[0]?.updated_at,
      });
      console.log("[SET CONVERSATIONS]", data.length);
      setConversations(data);
      console.log("[STATE UPDATED]", data.length);
      writeCachedConversations(data);
    } catch (e) {
      console.error("[MobileChatShell] fetchConversations:", e);
      const cached = readCachedConversations();
      if (cached.length > 0) setConversations(cached);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) fetchConversations();
  }, [authed, fetchConversations]);

  useEffect(() => {
    setNotifCount(getLocalNotifCount());
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ count?: number }>).detail;
      setNotifCount(
        typeof detail?.count === "number" ? detail.count : getLocalNotifCount(),
      );
    };
    window.addEventListener("wazza:mobile-notifs-updated", handler);
    return () =>
      window.removeEventListener("wazza:mobile-notifs-updated", handler);
  }, []);

  useEffect(() => {
    if (!authed) return;
    getAccountMe()
      .then((account) => setCurrentUserId(String(account.profile.id)))
      .catch(() => setCurrentUserId(null));
  }, [authed]);

  const fetchMessages = useCallback(async (convo: Conversation) => {
    try {
      const conversationId = String(convo.id);
      const data = await getMessagesByConversation(conversationId);

      if (selectedConvoIdRef.current !== conversationId) {
        return;
      }

      const fetchedMessages = data.map(toChatMessage);

      setMessages((prev) => {
        const fetchedIds = new Set(
          fetchedMessages.map((message) => message.id),
        );
        const realtimeMessages = prev.filter(
          (message) => !fetchedIds.has(message.id),
        );

        return [...fetchedMessages, ...realtimeMessages];
      });
    } catch (e) {
      console.error("[MobileChatShell] fetchMessages:", e);
    }
  }, []);

  const showBanner = useCallback((title: string, text: string) => {
    setPushBanner({ title, text });
    setTimeout(() => setPushBanner(null), 4000);
  }, []);

  const appendRealtimeMessage = useCallback((message: Message) => {
    const incoming = toChatMessage(message);

    setMessages((prev) => {
      if (prev.some((existing) => existing.id === incoming.id)) return prev;

      const optimisticIndex = prev.findIndex(
        (existing) =>
          existing.id.startsWith("opt-") &&
          existing.fromMe === incoming.fromMe &&
          existing.text === incoming.text,
      );

      if (optimisticIndex >= 0) {
        return prev.map((existing, index) =>
          index === optimisticIndex ? incoming : existing,
        );
      }

      return [...prev, incoming];
    });
  }, []);

  const showTeamNotification = useCallback(
    (payload: MobileRealtimePayload) => {
      if (
        normalizeRealtimeType(payload) !== "team_notification" &&
        payload.action !== "TEAM_NOTIFICATION_CREATED"
      )
        return false;

      console.log("[TEAM_NOTIFICATION EVENT]", payload);
      const details = getTeamNotificationDetails(payload);
      const now = Date.now();
      const lastSeen = teamNotificationDedupeRef.current.get(details.id);
      if (lastSeen && now - lastSeen < TEAM_NOTIFICATION_DEDUPE_WINDOW_MS)
        return true;

      teamNotificationDedupeRef.current.set(details.id, now);
      teamNotificationDedupeRef.current.forEach((timestamp, key) => {
        if (now - timestamp > TEAM_NOTIFICATION_DEDUPE_WINDOW_MS) {
          teamNotificationDedupeRef.current.delete(key);
        }
      });

      const priorityLabel = normalizePriorityLabel(details.priority);
      vibrate(
        details.priority === "high" || details.priority === "alta"
          ? [120, 60, 120]
          : [80],
      );
      showBanner(
        "🔔 Equipe notificada",
        [details.title, details.message, `Prioridade: ${priorityLabel}`]
          .filter(Boolean)
          .join(" · "),
      );
      addLocalNotif({
        title: `🔔 Equipe notificada · ${priorityLabel}`,
        body: [details.title, details.message].filter(Boolean).join(" — "),
        type: "team_notification",
        conversationId: details.conversationId || undefined,
      });

      if (
        details.conversationId &&
        selectedConvoIdRef.current === details.conversationId
      ) {
        const current = conversations.find(
          (c) => String(c.id) === details.conversationId,
        );
        if (current) void fetchMessages(current);
      }

      return true;
    },
    [conversations, fetchMessages, showBanner],
  );

  // ── WebSocket/SSE Hook ──────────────────────────────────────
  console.log("[BEFORE DASHBOARD HOOK MOBILE]");
  useRealtime({
    wsUrl: `${process.env.NEXT_PUBLIC_API_URL?.replace(/^https/, "wss").replace(/^http/, "ws")}/api/dashboard/ws`,
    sseUrl: `${process.env.NEXT_PUBLIC_API_URL}/api/dashboard/stream`,
    tenantId:
      typeof window !== "undefined"
        ? localStorage.getItem("tenant_id") || ""
        : "",
    onMessage: (data: unknown) => {
      console.log("[ONMESSAGE START]", data);
      console.log("[WS MESSAGE]", data);
      const d = data as MobileRealtimePayload;
      const type = normalizeRealtimeType(d) || "message";
      const refreshTargets = Array.isArray(d.refresh) ? d.refresh : [];

      showTeamNotification(d);

      if (refreshTargets.includes("conversations")) {
        console.log("[REFRESH CONVERSATIONS RECEIVED]");
        void fetchConversations().then(() => console.log("[FETCH FINISHED]"));
        return;
      }

      if (type === "conversation_updated" || type === "conversation_assigned") {
        const updated = ((d.conversation as
          | Partial<Conversation>
          | undefined) || d) as Partial<Conversation> & {
          id?: unknown;
          conversation_id?: unknown;
        };
        const updatedId =
          updated.id ?? updated.conversation_id ?? d.conversation_id;
        setConversations((prev) =>
          prev.map((c) =>
            String(c.id) === String(updatedId) ? { ...c, ...updated } : c,
          ),
        );
        if (
          selectedConvoId &&
          String(updatedId) === selectedConvoId &&
          updated.mode
        ) {
          setMode((updated.mode as string).toLowerCase() as ConversationMode);
        }
      }

      if (type === "new_message" || type === "message") {
        const msg = d as unknown as {
          conversation_id: unknown;
          message: Message;
        };
        vibrate([80, 40, 80]);
        setConversations((prev) =>
          prev.map((c) =>
            String(c.id) === String(msg.conversation_id)
              ? {
                  ...c,
                  last_message: msg.message?.content,
                  updated_at: msg.message?.created_at,
                }
              : c,
          ),
        );
        if (
          selectedConvoId &&
          String(msg.conversation_id) === selectedConvoId
        ) {
          appendRealtimeMessage(msg.message);
        }
      }

      if (type === "handoff_requested") {
        const h = d as { conversation_id: unknown; contact_name?: string };
        vibrate([120, 60, 120]);
        showBanner(
          "Solicitação de atendimento",
          `${h.contact_name || "Cliente"} quer falar com um humano`,
        );
        setConversations((prev) =>
          prev.map((c) =>
            String(c.id) === String(h.conversation_id)
              ? { ...c, mode: "human" }
              : c,
          ),
        );
      }

      if (type === "message_assigned") {
        const a = d as {
          conversation_id: unknown;
          user_name: string;
          user_id: string;
        };
        setConversations((prev) =>
          prev.map((c) =>
            String(c.id) === String(a.conversation_id)
              ? ({
                  ...c,
                  assigned_user_id: a.user_id,
                  assigned_user_name: a.user_name,
                } as any)
              : c,
          ),
        );
      }
    },
  });

  useEffect(() => {
    if (!selectedConvoId || view !== "chat" || typeof window === "undefined")
      return;

    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    const tenantId = localStorage.getItem("tenant_id") || "";
    const token = localStorage.getItem("token") || "";

    if (!apiUrl || !tenantId || !token) {
      console.warn(
        "[MOBILE MESSAGE WS] missing config/auth, skipping connection",
        {
          hasApiUrl: !!apiUrl,
          hasTenantId: !!tenantId,
          hasToken: !!token,
        },
      );
      return;
    }

    const wsBaseUrl = apiUrl
      .replace(/^https/, "wss")
      .replace(/^http/, "ws")
      .replace(/\/$/, "");

    const params = new URLSearchParams({
      tenant_id: tenantId,
      token,
    });

    const socket = new WebSocket(
      `${wsBaseUrl}/api/ws/messages/${encodeURIComponent(selectedConvoId)}?${params.toString()}`,
    );

    socket.onopen = () => {
      console.log("[MOBILE MESSAGE WS OPEN]", selectedConvoId);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as {
          event?: string;
          message?: Message;
          conversation_id?: unknown;
        };

        const type = payload.event || "message";
        const payloadConversationId = payload.conversation_id
          ? String(payload.conversation_id)
          : selectedConvoId;

        if (
          (type === "message" || type === "new_message") &&
          payload.message &&
          payloadConversationId === selectedConvoId
        ) {
          vibrate([80, 40, 80]);
          appendRealtimeMessage(payload.message);
        }
      } catch (error) {
        console.error("[MOBILE MESSAGE WS PARSE ERROR]", error);
      }
    };

    socket.onerror = (error) => {
      console.error("[MOBILE MESSAGE WS ERROR]", error);
    };

    socket.onclose = (event) => {
      console.log(
        "[MOBILE MESSAGE WS CLOSE]",
        selectedConvoId,
        event.code,
        event.reason,
      );
    };

    return () => {
      console.log("[MOBILE MESSAGE WS CLEANUP]", selectedConvoId);
      socket.close();
    };
  }, [appendRealtimeMessage, selectedConvoId, view]);

  useEffect(() => {
    writeCachedConversations(conversations);
  }, [conversations]);
  useEffect(() => {
    updateAppBadge(pendingCount);
  }, [pendingCount]);

  // ── Handlers ─────────────────────────────────────────────────
  const openChat = useCallback(
    (convoId: string) => {
      const convo = conversations.find((c) => c.id === convoId);
      if (!convo) return;
      selectedConvoIdRef.current = convoId;
      setSelectedConvoId(convoId);
      setMode((convo.mode?.toLowerCase() as ConversationMode) || "human");
      setMessages([]);
      fetchMessages(convo);
      setView("chat");
    },
    [conversations, fetchMessages],
  );

  const closeChat = useCallback(() => {
    setView("inbox");
    selectedConvoIdRef.current = null;
    setSelectedConvoId(null);
    setMessages([]);
  }, []);

  useEffect(() => {
    if (loading || conversations.length === 0 || typeof window === "undefined")
      return;
    const params = new URLSearchParams(window.location.search);
    const conversationId = params.get("conversation_id");
    if (!conversationId) return;
    openChat(conversationId);
    params.delete("conversation_id");
    const nextSearch = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}`,
    );
  }, [conversations, loading, openChat]);

  const handleSend = useCallback(
    async (e?: FormEvent) => {
      e?.preventDefault();
      const text = inputValue.trim();
      if (!text || !selectedConvo || !selectedContact) return;

      const optimistic: ChatMessage = {
        id: `opt-${Date.now()}`,
        text,
        fromMe: true,
        time: new Date().toLocaleTimeString("pt-BR", {
          hour: "2-digit",
          minute: "2-digit",
        }),
        createdAt: new Date().toISOString(),
        status: "sent",
        isNew: true,
      };
      setMessages((prev) => [...prev, optimistic]);
      setInputValue("");

      try {
        await sendMessage(selectedContact.phone, text, selectedContact.id);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === optimistic.id ? { ...m, status: "delivered" } : m,
          ),
        );
        setConversations((prev) =>
          prev.map((c) =>
            c.id === selectedConvo.id
              ? {
                  ...c,
                  last_message: text,
                  updated_at: new Date().toISOString(),
                }
              : c,
          ),
        );
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === optimistic.id ? { ...m, status: "sent" } : m,
          ),
        );
      }
    },
    [inputValue, selectedConvo, selectedContact],
  );

  const handleModeChange = useCallback(
    async (newMode: ConversationMode) => {
      if (!selectedConvo) return;
      setModeUpdating(true);
      try {
        await updateConversationMode(String(selectedConvo.id), newMode);
        setMode(newMode);
        setConversations((prev) =>
          prev.map((c) =>
            c.id === selectedConvo.id ? { ...c, mode: newMode } : c,
          ),
        );
      } finally {
        setModeUpdating(false);
      }
    },
    [selectedConvo],
  );

  const handleAssume = useCallback(async () => {
    if (!selectedConvo) return;
    try {
      console.log("[ASSUME SELECTED_CONVO_ID]", selectedConvoId);
      console.log("[ASSUME SELECTED_CONVO]", selectedConvo);
      console.log("[ASSUME CONVERSATIONS]", conversations);
      const response = await assignConversationToSelf(String(selectedConvo.id));
      const updatedConversation = response.conversation || {
        ...selectedConvo,
        mode: response.mode || "human",
        assigned_user_id:
          response.assigned_user_id || selectedConvo.assigned_user_id,
        assigned_user_name:
          response.assigned_user_name || selectedConvo.assigned_user_name,
      };
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConvo.id
            ? ({ ...c, ...updatedConversation } as any)
            : c,
        ),
      );
      setMode("human");
    } catch (e) {
      console.error("[MobileChatShell] handleAssume:", e);
    }
  }, [conversations, selectedConvo, selectedConvoId]);

  const handleRelease = useCallback(async () => {
    if (!selectedConvo) return;
    try {
      const response = await releaseConversationAssignment(
        String(selectedConvo.id),
      );
      const updatedConversation = response.conversation || {
        ...selectedConvo,
        mode: "bot",
        assigned_user_id: null,
        assigned_user_name: null,
      };
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConvo.id
            ? ({ ...c, ...updatedConversation } as any)
            : c,
        ),
      );
      setMode("bot");
    } catch (e) {
      console.error("[MobileChatShell] handleRelease:", e);
    }
  }, [selectedConvo]);

  const handleReset = useCallback(async () => {
    if (!selectedConvo) return;
    try {
      await fetch(`/api/admin/reset-conversation/${selectedConvo.id}`, {
        method: "POST",
        credentials: "include",
      });
      closeChat();
      fetchConversations();
    } catch (e) {
      console.error("[MobileChatShell] handleReset:", e);
    }
  }, [selectedConvo, fetchConversations, closeChat]);

  const handlePushAllow = useCallback(async () => {
    setShowPermSheet(false);
    await requestPermission();
    await subscribe();
  }, [requestPermission, subscribe]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "NOTIFICATION_CLICK" && e.data.conversation_id) {
        openChat(String(e.data.conversation_id));
      }
    };
    navigator.serviceWorker?.addEventListener("message", handler);
    return () =>
      navigator.serviceWorker?.removeEventListener("message", handler);
  }, [openChat]);

  // ── Render: loading hidratação ────────────────────────────────
  if (!authChecked) {
    return (
      <div
        style={{
          minHeight: "100dvh",
          background: "#FFFFFF",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: "40px",
            height: "40px",
            borderRadius: "12px",
            background: "#59C414",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            animation: "pulse 1.2s ease-in-out infinite",
          }}
        >
          <svg width="24" height="24" viewBox="0 0 36 36" fill="none">
            <path
              d="M18 2C9.16 2 2 9.16 2 18c0 2.77.74 5.36 2.04 7.61L2 34l8.59-1.98A15.9 15.9 0 0018 34c8.84 0 16-7.16 16-16S26.84 2 18 2z"
              fill="white"
            />
          </svg>
        </div>
        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
      </div>
    );
  }

  // ── Render: sem sessão → Login ────────────────────────────────
  if (!authed) {
    return <MobileLoginScreen onSuccess={() => setAuthed(true)} />;
  }

  // ── Render: Inbox ─────────────────────────────────────────────
  return (
    <div
      style={{
        fontFamily: "'DM Sans', sans-serif",
        WebkitFontSmoothing: "antialiased",
      }}
    >
      {view === "inbox" && (
        <MobileConvoList
          conversations={conversations}
          loading={loading}
          filter={filter}
          search={search}
          onFilterChange={setFilter}
          onSearchChange={setSearch}
          onSelectConvo={openChat}
          onPushRequest={() => setShowPermSheet(true)}
          pushGranted={pushGranted}
          pendingCount={pendingCount}
        />
      )}

      {view === "chat" && selectedContact && (
        <MobileChatView
          contact={selectedContact}
          messages={messages}
          inputValue={inputValue}
          onInputChange={setInputValue}
          onSend={handleSend}
          onBack={closeChat}
          mode={mode}
          modeUpdating={modeUpdating}
          onModeChange={handleModeChange}
          assignedUserName={assignedUserName}
          isAdmin={isAdmin}
          onAssume={handleAssume}
          onRelease={handleRelease}
          onReset={handleReset}
        />
      )}

      {view === "notifs" && <MobileNotifView />}

      {view === "profile" && (
        <MobileProfileView
          isInstallable={isInstallable}
          onInstall={promptInstall}
          pushGranted={pushGranted}
          onPushRequest={() => setShowPermSheet(true)}
        />
      )}

      {view !== "chat" && (
        <BottomNav
          current={view}
          onChange={setView}
          pendingCount={pendingCount}
          notifCount={notifCount}
        />
      )}

      {pushBanner && (
        <PushBanner
          title={pushBanner.title}
          text={pushBanner.text}
          onDismiss={() => setPushBanner(null)}
        />
      )}

      <PushPermissionSheet
        open={showPermSheet}
        onAllow={handlePushAllow}
        onDismiss={() => setShowPermSheet(false)}
      />

      {isInstallable && <InstallPrompt onInstall={promptInstall} />}
    </div>
  );
}
