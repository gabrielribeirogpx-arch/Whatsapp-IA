'use client';
type Event = { event_name: string; properties?: Record<string, unknown>; context?: Record<string, unknown>; idempotency_key?: string };
const enabled = () => process.env.NEXT_PUBLIC_PRODUCT_ANALYTICS_ENABLED !== 'false';
const queue: Event[] = []; let timer: ReturnType<typeof setTimeout> | undefined;
async function flush() { const batch=queue.splice(0,50); if (!batch.length || !enabled()) return; try { await fetch('/api/product-analytics/events/batch',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify({events:batch})}); } catch { /* analytics never affects navigation */ } }
export const productAnalytics={ track(event_name:string,properties:Record<string,unknown>={},context:Record<string,unknown>={}) { if(!enabled()) return; queue.push({event_name,properties,context:{route: typeof window==='undefined' ? '' : window.location.pathname,...context},idempotency_key:crypto.randomUUID?.()}); if(!timer) timer=setTimeout(()=>{timer=undefined;void flush();},800); }, flush };
