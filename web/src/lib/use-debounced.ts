"use client";

import { useEffect, useState } from "react";

/** `value`, but only once it has stayed the same for `delay` ms (e.g. a pause in typing). */
export function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
