import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: '/',
    name: 'Wazza API',
    short_name: 'Wazza API',
    description: 'Plataforma Wazza API para automação, atendimento e gestão de conversas com IA e operação humana.',
    start_url: '/dashboard',
    scope: '/',
    display: 'standalone',
        background_color: '#F8FAFC',
    theme_color: '#15803D',
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
       url: '/dashboard/inbox',
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