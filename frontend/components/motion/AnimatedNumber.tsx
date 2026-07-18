"use client";

import { useEffect, useRef, useState } from "react";

type AnimatedNumberProps = { value: number; duration?: number; formatter?: (value: number) => string; className?: string };

/** Interruption-safe count-up for live KPI values. */
export default function AnimatedNumber({ value, duration = 700, formatter = (number) => new Intl.NumberFormat("pt-BR").format(number), className }: AnimatedNumberProps) {
  const [displayValue, setDisplayValue] = useState(value);
  const previousValue = useRef(value);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { previousValue.current = value; setDisplayValue(value); return; }
    const from = previousValue.current; const startedAt = performance.now(); let frame = 0;
    const tick = (now: number) => { const progress = Math.min((now - startedAt) / duration, 1); const eased = 1 - Math.pow(1 - progress, 4); setDisplayValue(Math.round(from + (value - from) * eased)); if (progress < 1) frame = requestAnimationFrame(tick); else previousValue.current = value; };
    frame = requestAnimationFrame(tick); return () => cancelAnimationFrame(frame);
  }, [duration, value]);
  return <span className={className}>{formatter(displayValue)}</span>;
}
