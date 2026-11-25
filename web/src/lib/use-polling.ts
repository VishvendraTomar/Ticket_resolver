"use client";

import { useEffect, useEffectEvent } from "react";

/** Call `tick` every `ms` while `active` (e.g. while a version is being processed). */
export function usePolling(active: boolean, tick: () => void, ms = 2000): void {
  const onTick = useEffectEvent(tick);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => onTick(), ms);
    return () => clearInterval(id);
  }, [active, ms]);
}
