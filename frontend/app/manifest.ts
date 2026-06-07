import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: '/mobile',
    name: 'Wazza Inbox Enterprise',
    short_name: 'Wazza Inbox',
    description: 'Inbox mobile enterprise para atendimento WhatsApp com alertas em tempo real.',
    start_url: '/mobile',
    scope: '/mobile',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#0a0a0f',
    theme_color: '#0a0a0f',
    categories: ['business', 'productivity', 'communication'],
    lang: 'pt-BR',
    icons: [
      {
        src: '/Logo.svg',
        sizes: 'any',
        type: 'image/svg+xml',
        purpose: 'any',
      },
      {
        src: '/Logo.svg',
        sizes: 'any',
        type: 'image/svg+xml',
        purpose: 'any',
      },
      {
        src: '/Logo.svg',
        sizes: 'any',
        type: 'image/svg+xml',
        purpose: 'maskable',
      },
      {
        src: '/Logo.svg',
        sizes: 'any',
        type: 'image/svg+xml',
        purpose: 'maskable',
      },
    ],
    shortcuts: [
      {
        name: 'Abrir Inbox',
        short_name: 'Inbox',
        description: 'Abrir a lista de conversas mobile.',
        url: '/mobile',
        icons: [{ src: '/Logo.svg', sizes: 'any', type: 'image/svg+xml' }],
      },
    ],
  };
}
