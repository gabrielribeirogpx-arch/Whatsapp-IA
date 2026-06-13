"use client";

/**
 * BottomNav.tsx — Wazza Inbox Mobile
 * Light Mode · Identidade Verde #59C414
 */

import { MessageSquare, Bell, User } from "lucide-react";
import type { MobileView } from "../MobileChatShell";

interface BottomNavProps {
  current: MobileView;
  onChange: (view: MobileView) => void;
  pendingCount?: number;
  notifCount?: number;
}

export default function BottomNav({
  current,
  onChange,
  pendingCount = 0,
  notifCount = 0,
}: BottomNavProps) {
  const tabs: {
    id: MobileView;
    label: string;
    icon: React.ReactNode;
    badge?: number;
  }[] = [
    {
      id: "inbox",
      label: "Inbox",
      icon: <MessageSquare size={22} />,
      badge: pendingCount > 0 ? pendingCount : undefined,
    },
    {
      id: "notifs",
      label: "Alertas",
      icon: <Bell size={22} />,
      badge: notifCount > 0 ? notifCount : undefined,
    },
    { id: "profile", label: "Perfil", icon: <User size={22} /> },
  ];

  return (
    <nav
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        height: "64px",
        background: "#FFFFFF",
        borderTop: "1px solid #E5E7EB",
        display: "flex",
        alignItems: "stretch",
        zIndex: 100,
        paddingBottom: "env(safe-area-inset-bottom)",
      }}
    >
      {tabs.map((tab) => {
        const active = current === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: "3px",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: active ? "#59C414" : "#9CA3AF",
              transition: "color 0.15s",
              position: "relative",
              WebkitTapHighlightColor: "transparent",
            }}
          >
            {/* Active indicator top */}
            {active && (
              <span
                style={{
                  position: "absolute",
                  top: 0,
                  left: "50%",
                  transform: "translateX(-50%)",
                  width: "32px",
                  height: "2px",
                  background: "#59C414",
                  borderRadius: "0 0 2px 2px",
                }}
              />
            )}

            {/* Icon with badge */}
            <span style={{ position: "relative" }}>
              {tab.icon}
              {tab.badge !== undefined && (
                <span
                  style={{
                    position: "absolute",
                    top: "-4px",
                    right: "-6px",
                    minWidth: "16px",
                    height: "16px",
                    padding: "0 4px",
                    background: "#e24b4a",
                    borderRadius: "8px",
                    fontSize: "10px",
                    fontWeight: 600,
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    lineHeight: 1,
                  }}
                >
                  {tab.badge > 99 ? "99+" : tab.badge}
                </span>
              )}
            </span>

            <span style={{ fontSize: "10px", fontWeight: active ? 600 : 400 }}>
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
