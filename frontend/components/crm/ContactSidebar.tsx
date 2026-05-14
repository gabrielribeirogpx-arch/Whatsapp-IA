'use client';

export default function ContactSidebar({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className='rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm'><h3 className='mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500'>{title}</h3>{children}</section>;
}
