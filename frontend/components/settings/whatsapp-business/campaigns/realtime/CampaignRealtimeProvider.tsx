import { useEffect, useRef, useState } from 'react';
import { listWhatsAppCampaigns } from '@/lib/api';
import { WhatsAppCampaign } from '@/lib/types';

const ACTIVE = new Set(['scheduled', 'running', 'paused']);

export function useCampaignRealtime(campaigns: WhatsAppCampaign[], onUpdate: (campaigns: WhatsAppCampaign[]) => void) {
  const [state, setState] = useState<'idle' | 'polling' | 'stale'>('idle');
  const inFlight = useRef(false);
  const hasActive = campaigns.some((c) => ACTIVE.has(c.status));
  useEffect(() => {
    if (!hasActive) { setState('idle'); return undefined; }
    let stopped = false;
    let delay = 5000;
    let timeout: number | undefined;
    const tick = async () => {
      if (stopped) return;
      if (document.visibilityState !== 'visible' || inFlight.current) { timeout = window.setTimeout(tick, delay); return; }
      inFlight.current = true; setState('polling');
      try { onUpdate(await listWhatsAppCampaigns()); delay = 5000; }
      catch { setState('stale'); delay = Math.min(delay * 2, 30000); }
      finally { inFlight.current = false; timeout = window.setTimeout(tick, delay); }
    };
    timeout = window.setTimeout(tick, 5000);
    return () => { stopped = true; if (timeout) window.clearTimeout(timeout); };
  }, [hasActive, onUpdate]);
  return state;
}
