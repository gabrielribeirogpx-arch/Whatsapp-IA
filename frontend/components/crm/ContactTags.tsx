'use client';
import { memo } from 'react';

type Props = { tags: string[]; onRemove?: (tag: string) => void };

function ContactTags({ tags, onRemove }: Props) {
  if (!tags?.length) return <p className='text-sm text-slate-400'>Sem tags</p>;
  return <div className='flex flex-wrap gap-2'>
    {tags.map((tag) => <button key={tag} onClick={() => onRemove?.(tag)} className='rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 transition hover:scale-[1.03] hover:bg-indigo-100'>#{tag}</button>)}
  </div>;
}

export default memo(ContactTags);
