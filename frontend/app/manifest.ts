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
    background_color: '#FFFFFF',
    theme_color: '#FFFFFF',
    categories: ['business', 'productivity', 'communication'],
    lang: 'pt-BR',
    icons: [
      {
        src: '/icons/icon-192x192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/icons/icon-512x512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/icons/icon-maskable-192x192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'maskable',
      },
      {
        src: '/icons/icon-maskable-512x512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable',
      },
      ], 
    shortcuts: [
      {
       name: 'Abrir Inbox',
       short_name: 'Inbox',
       description: 'Abrir conversas',
       url: '/mobile',
       icons: [
        {
          src: '/icons/icon-192x192.png',
          sizes: '192x192',
          type: 'image/png',
     },
    ],
  },
],

  };
}