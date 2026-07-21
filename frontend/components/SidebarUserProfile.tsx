"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Bell,
  Building2,
  ChevronRight,
  CreditCard,
  Layers3,
  LockKeyhole,
  LogOut,
  ShieldCheck,
  Sparkles,
  User,
  UsersRound,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getAccountMe, getTenantSessionFromStorage } from "@/lib/api";
import { getUserDisplayName } from "@/lib/userDisplayName";

type SidebarUserProfileProps = {
  expanded: boolean;
};

type SessionSnapshot = {
  email?: string;
  name: string;
  initials: string;
  role: string;
  workspace: string;
};

type MenuItem = {
  label: string;
  description: string;
  href?: string;
  icon: typeof User;
  variant?: "danger";
  onClick?: () => void;
};

type MenuGroup = {
  title: string;
  items: MenuItem[];
};

const FALLBACK_SESSION: SessionSnapshot = {
  name: "Admin Wazza",
  initials: "WA",
  role: "Owner",
  workspace: "Workspace ativo",
};

function safeDecodeTokenPayload(
  token?: string,
): Record<string, unknown> | null {
  if (!token) return null;

  const payload = token.split(".")[0];
  if (!payload) return null;

  try {
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(
      normalized.length + ((4 - (normalized.length % 4)) % 4),
      "=",
    );
    return JSON.parse(window.atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function titleCase(value: string) {
  return value
    .split(/[\s._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function getInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "WA";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function getSessionSnapshot(): SessionSnapshot {
  if (typeof window === "undefined") return FALLBACK_SESSION;

  const session = getTenantSessionFromStorage();
  const payload = safeDecodeTokenPayload(session?.token);
  const email = typeof payload?.email === "string" ? payload.email : undefined;
  const emailName = email ? titleCase(email.split("@")[0] || email) : undefined;
  const slug = session?.slug ? titleCase(session.slug) : undefined;
  const tenantId = session?.tenant_id
    ? `Tenant ${session.tenant_id.slice(0, 8)}`
    : undefined;
  const name = emailName || FALLBACK_SESSION.name;

  return {
    email,
    name,
    initials: getInitials(name),
    role: "Owner · Admin",
    workspace: slug || tenantId || FALLBACK_SESSION.workspace,
  };
}

export default function SidebarUserProfile({
  expanded,
}: SidebarUserProfileProps) {
  const router = useRouter();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const firstMenuItemRef = useRef<HTMLAnchorElement | null>(null);
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [session, setSession] = useState<SessionSnapshot>(FALLBACK_SESSION);

  useEffect(() => {
    setSession(getSessionSnapshot());

    let active = true;
    getAccountMe()
      .then(({ profile }) => {
        if (!active) return;
        const name = getUserDisplayName(profile);
        if (!name) return;
        setSession((current) => ({
          ...current,
          email: profile.email || current.email,
          name,
          initials: getInitials(name),
          role: profile.role || current.role,
        }));
      })
      .catch(() => {
        // Preserve the existing session-based fallback when the profile is unavailable.
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const updateViewport = () =>
      setIsMobile(window.matchMedia("(max-width: 760px)").matches);
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  const syncMenuPosition = useCallback(() => {
    const button = buttonRef.current;
    if (!button || isMobile) return;

    const rect = button.getBoundingClientRect();
    const menuHeight = 640;
    const top = Math.max(
      12,
      Math.min(rect.bottom - menuHeight, window.innerHeight - menuHeight - 12),
    );
    setMenuPosition({
      top,
      left: rect.right + 12,
    });
  }, [isMobile]);

  const handleTriggerClick = () => {
    if (!open && !isMobile) {
      syncMenuPosition();
    }

    setOpen((current) => !current);
  };

  useEffect(() => {
    if (!open) return;
    syncMenuPosition();
    window.addEventListener("resize", syncMenuPosition);
    window.addEventListener("scroll", syncMenuPosition, true);
    return () => {
      window.removeEventListener("resize", syncMenuPosition);
      window.removeEventListener("scroll", syncMenuPosition, true);
    };
  }, [open, syncMenuPosition]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        buttonRef.current?.contains(target) ||
        menuRef.current?.contains(target)
      )
        return;
      setOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;

    firstMenuItemRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open || !isMobile) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open, isMobile]);

  const handleLogout = useCallback(() => {
    window.localStorage.removeItem("tenant");
    window.localStorage.removeItem("token");
    window.localStorage.removeItem("tenant_id");
    setOpen(false);
    router.push("/login");
  }, [router]);

  const groups = useMemo<MenuGroup[]>(
    () => [
      {
        title: "Conta",
        items: [
          {
            label: "Meu perfil",
            description: "Dados, avatar e identidade",
            href: "/dashboard/account?tab=profile",
            icon: User,
          },
          {
            label: "Preferências",
            description: "Notificações e experiência",
            href: "/dashboard/account?tab=preferences",
            icon: Bell,
          },
          {
            label: "Segurança",
            description: "Sessões e proteção da conta",
            href: "/dashboard/account?tab=security",
            icon: LockKeyhole,
          },
        ],
      },
      {
        title: "Workspace",
        items: [
          {
            label: "Usuários",
            description: "Convites, seats e time",
            href: "/dashboard/account?tab=users",
            icon: UsersRound,
          },
          {
            label: "Permissões",
            description: "Papéis e políticas de acesso",
            href: "/dashboard/account?tab=permissions",
            icon: ShieldCheck,
          },
          {
            label: "Billing",
            description: "Plano, faturas e limites",
            href: "/dashboard/account?tab=billing",
            icon: CreditCard,
          },
        ],
      },
      {
        title: "Sessão",
        items: [
          {
            label: "Logout",
            description: "Encerrar sessão com segurança",
            icon: LogOut,
            variant: "danger",
            onClick: handleLogout,
          },
        ],
      },
    ],
    [handleLogout],
  );

  const menu = (
    <div
      ref={menuRef}
      className={`sidebar-account-menu ${isMobile ? "is-mobile" : ""} ${open ? "is-open" : ""}`}
      style={
        isMobile
          ? undefined
          : { top: menuPosition.top, left: menuPosition.left }
      }
      role="menu"
      id={menuId}
      aria-label="Menu de conta e workspace"
    >
      <div className="sidebar-account-menu-header">
        <div className="sidebar-account-avatar is-large" aria-hidden="true">
          {session.initials}
        </div>
        <div className="sidebar-account-menu-identity">
          <strong>{session.name}</strong>
          <span>{session.email || session.role}</span>
        </div>
        <div className="sidebar-account-status">
          <Sparkles size={14} aria-hidden="true" />
          Pro
        </div>
      </div>

      <div className="sidebar-account-workspace-card">
        <Building2 size={16} aria-hidden="true" />
        <div>
          <span>Workspace</span>
          <strong>{session.workspace}</strong>
        </div>
      </div>

      <div className="sidebar-account-menu-groups">
        {groups.map((group) => (
          <section
            key={group.title}
            className="sidebar-account-menu-group"
            aria-label={group.title}
          >
            <p>{group.title}</p>
            {group.items.map((item) => {
              const Icon = item.icon;
              const className = `sidebar-account-menu-item ${item.variant === "danger" ? "is-danger" : ""}`;
              const content = (
                <>
                  <span className="sidebar-account-menu-icon">
                    <Icon size={16} aria-hidden="true" />
                  </span>
                  <span className="sidebar-account-menu-copy">
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                  <ChevronRight
                    className="sidebar-account-menu-chevron"
                    size={15}
                    aria-hidden="true"
                  />
                </>
              );

              if (item.href) {
                return (
                  <Link
                    key={item.label}
                    ref={item.label === "Meu perfil" ? firstMenuItemRef : undefined}
                    href={item.href}
                    className={className}
                    role="menuitem"
                    onClick={() => setOpen(false)}
                  >
                    {content}
                  </Link>
                );
              }

              return (
                <button
                  key={item.label}
                  type="button"
                  className={className}
                  role="menuitem"
                  onClick={item.onClick}
                >
                  {content}
                </button>
              );
            })}
          </section>
        ))}
      </div>
    </div>
  );

  return (
    <div className={`sidebar-user-profile ${expanded ? "is-expanded" : ""}`}>
      <button
        ref={buttonRef}
        type="button"
        className="sidebar-user-profile-trigger"
        onClick={handleTriggerClick}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label="Abrir menu de conta"
      >
        <span className="sidebar-account-avatar" aria-hidden="true">
          {session.initials}
        </span>
        <span className="sidebar-user-profile-copy">
          <strong>{session.name}</strong>
          <small>{session.role}</small>
          <em>{session.workspace}</em>
        </span>
        <ChevronRight
          className="sidebar-user-profile-chevron"
          size={16}
          aria-hidden="true"
        />
      </button>

      {open && typeof document !== "undefined"
        ? createPortal(
            <>
              <div
                className={`sidebar-account-backdrop ${isMobile ? "is-mobile" : ""}`}
                aria-hidden="true"
              />
              {menu}
            </>,
            document.body,
          )
        : null}
    </div>
  );
}
