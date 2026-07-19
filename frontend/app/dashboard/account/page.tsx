import { Suspense } from 'react';
import AccountPageClient from '@/components/account/AccountPageClient';
import { FormSkeleton } from '@/components/ui/loading';

export default function AccountPage() {
  return (
    <Suspense fallback={<FormSkeleton />}>
      <AccountPageClient />
    </Suspense>
  );
}
