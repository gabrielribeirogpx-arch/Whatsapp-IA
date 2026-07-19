import { Suspense } from 'react';
import SettingsPageClient from '@/components/settings/SettingsPageClient';
import { FormSkeleton } from '@/components/ui/loading';

export default function SettingsPage() {
  return (
    <Suspense fallback={<FormSkeleton />}>
      <SettingsPageClient />
    </Suspense>
  );
}
