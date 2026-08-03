"use client";

import { useSyncExternalStore } from "react";

export const DEVELOPER_MODE_STORAGE_KEY = "wazza.developer-mode";
const DEVELOPER_MODE_EVENT = "wazza:developer-mode-change";

function subscribe(onStoreChange: () => void) {
  window.addEventListener(DEVELOPER_MODE_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);
  return () => {
    window.removeEventListener(DEVELOPER_MODE_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getSnapshot() {
  return window.localStorage.getItem(DEVELOPER_MODE_STORAGE_KEY) === "true";
}

export function setDeveloperMode(enabled: boolean) {
  window.localStorage.setItem(DEVELOPER_MODE_STORAGE_KEY, String(enabled));
  window.dispatchEvent(new Event(DEVELOPER_MODE_EVENT));
}

export function useDeveloperMode() {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
