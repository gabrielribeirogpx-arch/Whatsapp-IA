'use client';

/**
 * /frontend/components/mobile/MobileProfileView.tsx
 * Perfil do atendente: toggle push, botão instalar, info do app.
 */

import { Bell, BellOff, Download, CheckCircle, LogOut, Smartphone } from 'lucide-react';

interface MobileProfileViewProps {
  isInstallable: boolean;
  onInstall: () => Promise<boolean>;
  pushGranted: boolean;
  onPushRequest: () => void;
}

export default function MobileProfileView({
  isInstallable,
  onInstall,
  pushGranted,
  onPushRequest,
}: MobileProfileViewProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100dvh',
        background: '#0a0a0f',
        fontFamily: "'DM Sans', sans-serif",
        overflowY: 'auto',
        paddingBottom: 'calc(env(safe-area-inset-bottom,0px) + 72px)',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: 'calc(env(safe-area-inset-top,0px) + 14px) 16px 14px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          flexShrink: 0,
        }}
      >
        <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#e8e8f0', letterSpacing: '-0.3px' }}>
          Perfil
        </h1>
      </div>

      {/* Avatar placeholder */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: '28px 20px 20px',
          gap: '8px',
        }}
      >
        <div
          style={{
            width: '72px',
            height: '72px',
            borderRadius: '50%',
            background: 'rgba(124,110,245,0.15)',
            border: '2px solid rgba(124,110,245,0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '26px',
            fontWeight: 700,
            color: '#7c6ef5',
          }}
        >
          A
        </div>
        <p style={{ margin: 0, fontSize: '17px', fontWeight: 600, color: '#e8e8f0' }}>
          Atendente
        </p>
        <p style={{ margin: 0, fontSize: '12px', color: 'rgba(255,255,255,0.3)' }}>
          Operador · Wazza Inbox
        </p>
      </div>

      {/* Section: Notificações */}
      <Section title="Notificações">
        <SettingRow
          icon={pushGranted ? <Bell size={18} /> : <BellOff size={18} />}
          label="Notificações push"
          value={pushGranted ? 'Ativadas' : 'Desativadas'}
          valueColor={pushGranted ? '#1D9E75' : 'rgba(255,255,255,0.3)'}
          onClick={onPushRequest}
          actionLabel={pushGranted ? undefined : 'Ativar'}
        />
      </Section>

      {/* Section: App */}
      <Section title="Aplicativo">
        {isInstallable && (
          <SettingRow
            icon={<Download size={18} />}
            label="Instalar na tela inicial"
            value="Disponível"
            valueColor="#7c6ef5"
            onClick={onInstall}
            actionLabel="Instalar"
          />
        )}
        {!isInstallable && (
          <SettingRow
            icon={<CheckCircle size={18} />}
            label="Instalado como app"
            value="Wazza Inbox"
            valueColor="#1D9E75"
          />
        )}
        <SettingRow
          icon={<Smartphone size={18} />}
          label="Versão"
          value="1.0.0"
          valueColor="rgba(255,255,255,0.3)"
        />
      </Section>

      {/* Section: Conta */}
      <Section title="Conta">
        <SettingRow
          icon={<LogOut size={18} />}
          label="Sair"
          value=""
          danger
          onClick={() => {
            if (typeof window !== 'undefined') {
              window.location.href = '/logout';
            }
          }}
        />
      </Section>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: '8px' }}>
      <p
        style={{
          margin: '0 0 4px',
          padding: '0 16px',
          fontSize: '11px',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.07em',
          color: 'rgba(255,255,255,0.3)',
        }}
      >
        {title}
      </p>
      <div style={{ background: '#0d0d14', borderTop: '1px solid rgba(255,255,255,0.05)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        {children}
      </div>
    </div>
  );
}

interface SettingRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueColor?: string;
  onClick?: (() => void) | (() => Promise<boolean>);
  actionLabel?: string;
  danger?: boolean;
}

function SettingRow({ icon, label, value, valueColor, onClick, actionLabel, danger }: SettingRowProps) {
  return (
    <div
      onClick={onClick as () => void}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '14px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        cursor: onClick ? 'pointer' : 'default',
        WebkitTapHighlightColor: onClick ? 'rgba(124,110,245,0.06)' : 'transparent',
      }}
    >
      <span style={{ color: danger ? '#e24b4a' : 'rgba(255,255,255,0.4)', flexShrink: 0 }}>
        {icon}
      </span>
      <span style={{ flex: 1, fontSize: '14px', color: danger ? '#e24b4a' : '#e8e8f0' }}>
        {label}
      </span>
      {value && (
        <span style={{ fontSize: '13px', color: valueColor || 'rgba(255,255,255,0.4)' }}>
          {value}
        </span>
      )}
      {actionLabel && (
        <span
          style={{
            fontSize: '12px',
            padding: '3px 10px',
            background: 'rgba(124,110,245,0.15)',
            borderRadius: '20px',
            color: '#7c6ef5',
            fontWeight: 600,
          }}
        >
          {actionLabel}
        </span>
      )}
    </div>
  );
}
