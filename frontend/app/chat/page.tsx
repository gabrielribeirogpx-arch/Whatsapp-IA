"use client";

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import ChatShell from '../../components/chat-shell';

function ChatPageContent() {
  useSearchParams();
  return <ChatShell />;
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-500">Carregando inbox...</div>}>
      <ChatPageContent />
    </Suspense>
  );
}
