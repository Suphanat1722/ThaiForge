import { useEffect, useRef } from "react";

export function usePolling(
  callback: (signal: AbortSignal) => Promise<void>,
  delay: number,
  enabled = true,
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return;
    let timer = 0;
    let controller: AbortController | null = null;

    const schedule = () => {
      window.clearTimeout(timer);
      if (!document.hidden) {
        timer = window.setTimeout(run, delay);
      }
    };
    const run = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        await callbackRef.current(controller.signal);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) throw error;
      } finally {
        schedule();
      }
    };
    const onVisibility = () => {
      controller?.abort();
      if (!document.hidden) void run();
      else window.clearTimeout(timer);
    };

    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [delay, enabled]);
}

