'use client';

import { useCallback, useEffect, useState } from 'react';

type PushSubscribeResult = PushSubscription | null;

function urlBase64ToUint8Array(base64String: string) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = `${base64String}${padding}`.replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  return Uint8Array.from(Array.from(rawData).map((char) => char.charCodeAt(0)));
}

async function notifyBackend(subscription: PushSubscription) {
  const endpoint = process.env.NEXT_PUBLIC_PUSH_SUBSCRIBE_URL || '/api/push/subscriptions';
  try {
    await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(subscription.toJSON()),
    });
  } catch (error) {
    console.warn('[PWA] Subscription push criada localmente, mas backend não confirmou:', error);
  }
}

export function usePushNotifications() {
  const [permission, setPermission] = useState<NotificationPermission>('default');
  const [subscription, setSubscription] = useState<PushSubscribeResult>(null);
  const [supported, setSupported] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const hasSupport = 'Notification' in window && 'serviceWorker' in navigator && 'PushManager' in window;
    setSupported(hasSupport);
    if (!hasSupport) return;

    setPermission(Notification.permission);
    navigator.serviceWorker.ready
      .then((registration) => registration.pushManager.getSubscription())
      .then(setSubscription)
      .catch((error) => console.warn('[PWA] Não foi possível ler subscription push:', error));
  }, []);

  const requestPermission = useCallback(async () => {
    if (!supported) return false;
    const result = await Notification.requestPermission();
    setPermission(result);
    return result === 'granted';
  }, [supported]);

  const subscribe = useCallback(async () => {
    if (!supported) return null;

    const currentPermission = permission === 'granted' ? permission : await Notification.requestPermission();
    setPermission(currentPermission);
    if (currentPermission !== 'granted') return null;

    const registration = await navigator.serviceWorker.ready;
    const existing = await registration.pushManager.getSubscription();
    if (existing) {
      setSubscription(existing);
      await notifyBackend(existing);
      return existing;
    }

    const publicKey = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY;
    if (!publicKey) {
      console.warn('[PWA] NEXT_PUBLIC_VAPID_PUBLIC_KEY não configurada; push remoto não será assinado.');
      return null;
    }

    const created = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
    setSubscription(created);
    await notifyBackend(created);
    return created;
  }, [permission, supported]);

  return {
    supported,
    granted: permission === 'granted',
    permission,
    subscription,
    requestPermission,
    subscribe,
  };
}
