import { useCallback, useRef } from 'react';
import { AppState, InteractionManager } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';

type LoadOpts = { silent?: boolean; reason?: string };

/**
 * Owner-friendly polling: keep previous data visible, only spin RefreshControl on
 * explicit pull-to-refresh, cancel in-flight work on blur/unmount, and defer the
 * first fetch until after the navigation transition finishes.
 */
export function useSilentRefresh(
  load: (opts: LoadOpts, signal: AbortSignal) => Promise<void>,
  opts?: { intervalMs?: number; loadOnFocus?: boolean; deferMs?: number },
) {
  const intervalMs = opts?.intervalMs ?? 0;
  const loadOnFocus = opts?.loadOnFocus !== false;
  const deferMs = opts?.deferMs ?? 0;
  const loadRef = useRef(load);
  loadRef.current = load;
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (silent: boolean) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await loadRef.current({ silent, reason: silent ? 'poll' : 'user' }, ac.signal);
    } catch (e: any) {
      if (e?.name === 'AbortError' || ac.signal.aborted) return;
      throw e;
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      let intervalId: ReturnType<typeof setInterval> | null = null;
      let interactionHandle: { cancel: () => void } | null = null;
      let deferTimer: ReturnType<typeof setTimeout> | null = null;

      if (loadOnFocus) {
        interactionHandle = InteractionManager.runAfterInteractions(() => {
          if (cancelled) return;
          const kick = () => {
            run(true).catch(() => {});
          };
          if (deferMs > 0) deferTimer = setTimeout(kick, deferMs);
          else kick();
        });
      }

      if (intervalMs > 0) {
        intervalId = setInterval(() => {
          if (AppState.currentState !== 'active') return;
          run(true).catch(() => {});
        }, intervalMs);
      }

      return () => {
        cancelled = true;
        interactionHandle?.cancel?.();
        if (deferTimer) clearTimeout(deferTimer);
        if (intervalId) clearInterval(intervalId);
        abortRef.current?.abort();
      };
    }, [run, intervalMs, loadOnFocus, deferMs]),
  );

  const refresh = useCallback(() => run(false), [run]);
  const silentRefresh = useCallback(() => run(true), [run]);

  return { refresh, silentRefresh, abortRef };
}
