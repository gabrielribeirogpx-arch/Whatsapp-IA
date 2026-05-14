"use client";

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import ChatShell from '@/components/chat-shell';

function InboxPageContent() {
  useSearchParams();
  return <ChatShell />;
}

export default function InboxPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-500">Carregando inbox...</div>}>
      <InboxPageContent />
    </Suspense>
  );
}
