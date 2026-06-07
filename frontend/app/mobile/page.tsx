/**
 * /frontend/app/mobile/offline/page.tsx
 * Página de fallback offline — servida pelo Service Worker quando
 * não há conexão e o recurso não está em cache.
 */

export default function MobileOfflinePage() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100dvh',
        background: '#0a0a0f',
        fontFamily: "'DM Sans', sans-serif",
        padding: '24px',
        textAlign: 'center',
        gap: '16px',
      }}
    >
      {/* Icon */}
      <div
        style={{
          width: '64px',
          height: '64px',
          borderRadius: '18px',
          background: 'rgba(239,159,39,0.12)',
          border: '1px solid rgba(239,159,39,0.25)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '28px',
        }}
      >
        📡
      </div>

      <h1
        style={{
          margin: 0,
          fontSize: '20px',
          fontWeight: 700,
          color: '#e8e8f0',
          letterSpacing: '-0.3px',
        }}
      >
        Sem conexão
      </h1>

      <p
        style={{
          margin: 0,
          fontSize: '14px',
          color: 'rgba(255,255,255,0.4)',
          maxWidth: '260px',
          lineHeight: 1.6,
        }}
      >
        Verifique sua conexão com a internet e tente novamente.
      </p>

      <button
        onClick={() => window.location.reload()}
        style={{
          marginTop: '8px',
          padding: '12px 28px',
          background: '#7c6ef5',
          border: 'none',
          borderRadius: '12px',
          fontSize: '14px',
          fontWeight: 600,
          color: '#fff',
          cursor: 'pointer',
        }}
      >
        Tentar novamente
      </button>
    </div>
  );
}
