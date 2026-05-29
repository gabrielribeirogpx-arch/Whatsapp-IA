import { Suspense } from 'react';
import SettingsPageClient from '@/components/settings/SettingsPageClient';

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className='p-8 text-sm text-slate-500'>Carregando configurações...</div>}>
      <SettingsPageClient />
    </Suspense>
  );
}
