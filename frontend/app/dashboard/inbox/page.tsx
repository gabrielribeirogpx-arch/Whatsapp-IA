"use client";

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import ChatShell from '@/components/chat-shell';
import { InboxSkeleton } from '@/components/ui/loading';

function InboxPageContent() {
  useSearchParams();
  return <ChatShell />;
}

export default function InboxPage() {
  return (
    <Suspense fallback={<InboxSkeleton />}>
      <InboxPageContent />
    </Suspense>
  );
}
