import { Suspense } from 'react';
import AccountPageClient from '@/components/account/AccountPageClient';

export default function AccountPage() {
  return (
    <Suspense fallback={<div className='p-8 text-sm text-slate-500'>Carregando conta...</div>}>
      <AccountPageClient />
    </Suspense>
  );
}
