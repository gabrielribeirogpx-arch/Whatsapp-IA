'use client';
import { useEffect, useRef, useState } from 'react';
export function useDelayedLoading(loading: boolean, { delay = 180, minimumDuration = 320 }: { delay?: number; minimumDuration?: number } = {}) {
  const [visible, setVisible] = useState(false); const shownAt = useRef<number | null>(null);
  useEffect(() => { let timer: ReturnType<typeof setTimeout> | undefined;
    if (loading) timer = setTimeout(() => { shownAt.current = Date.now(); setVisible(true); }, delay);
    else if (shownAt.current) { const remaining = Math.max(0, minimumDuration - (Date.now() - shownAt.current)); timer = setTimeout(() => { shownAt.current = null; setVisible(false); }, remaining); }
    else setVisible(false);
    return () => { if (timer) clearTimeout(timer); };
  }, [loading, delay, minimumDuration]); return visible;
}
