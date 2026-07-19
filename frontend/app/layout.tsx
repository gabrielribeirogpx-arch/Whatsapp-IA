import './globals.css';
import type { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'Wazza API',
  applicationName: 'Wazza API',
  description: 'Plataforma Wazza API para automação, atendimento e gestão de conversas com IA e operação humana.',
  openGraph: {
    title: 'Wazza API',
    description: 'Plataforma Wazza API para automação, atendimento e gestão de conversas com IA e operação humana.',
    siteName: 'Wazza API',
  },
  twitter: {
    card: 'summary',
    title: 'Wazza API',
    description: 'Plataforma Wazza API para automação, atendimento e gestão de conversas com IA e operação humana.',
  }
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#ffffff',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
