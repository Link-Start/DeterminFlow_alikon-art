import { useCallback, useEffect, useRef, type RefObject } from "react";

export interface ScrollMetrics {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}

export function distanceFromBottom(metrics: ScrollMetrics): number {
  return Math.max(0, metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight);
}

export function maxScrollTop(metrics: Pick<ScrollMetrics, "scrollHeight" | "clientHeight">): number {
  return Math.max(0, metrics.scrollHeight - metrics.clientHeight);
}

export function isNearBottom(metrics: ScrollMetrics, threshold = 160): boolean {
  return distanceFromBottom(metrics) <= threshold;
}

export function followStateAfterScroll(args: {
  wasFollowing: boolean;
  programmatic: boolean;
  metrics: ScrollMetrics;
  threshold?: number;
}): boolean {
  if (args.programmatic) return args.wasFollowing;
  return isNearBottom(args.metrics, args.threshold);
}

export function applyFollowOutputScroll<T extends ScrollMetrics>(viewport: T): number {
  const nextTop = maxScrollTop(viewport);
  viewport.scrollTop = nextTop;
  return nextTop;
}

export interface UseAutoFollowOutputOptions {
  threshold?: number;
}

export interface UseAutoFollowOutputReturn {
  scrollToBottom: (force?: boolean) => void;
  resetAutoFollow: () => void;
  isFollowingOutput: () => boolean;
}

export function useAutoFollowOutput<T extends HTMLElement>(
  viewportRef: RefObject<T | null>,
  { threshold = 160 }: UseAutoFollowOutputOptions = {},
): UseAutoFollowOutputReturn {
  const shouldFollowRef = useRef(true);
  const programmaticScrollRef = useRef(false);
  const animationFrameRef = useRef<number | null>(null);

  const cancelScheduledScroll = useCallback(() => {
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  }, []);

  const scrollToBottom = useCallback((force = false) => {
    const viewport = viewportRef.current;
    if (!viewport || (!force && !shouldFollowRef.current)) return;
    if (animationFrameRef.current !== null) return;

    animationFrameRef.current = requestAnimationFrame(() => {
      animationFrameRef.current = null;
      const currentViewport = viewportRef.current;
      if (!currentViewport || (!force && !shouldFollowRef.current)) return;
      programmaticScrollRef.current = true;
      applyFollowOutputScroll(currentViewport);
      programmaticScrollRef.current = false;
      if (force) shouldFollowRef.current = true;
    });
  }, [viewportRef]);

  const resetAutoFollow = useCallback(() => {
    shouldFollowRef.current = true;
    scrollToBottom(true);
  }, [scrollToBottom]);

  const isFollowingOutput = useCallback(() => shouldFollowRef.current, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const handleScroll = () => {
      shouldFollowRef.current = followStateAfterScroll({
        wasFollowing: shouldFollowRef.current,
        programmatic: programmaticScrollRef.current,
        metrics: viewport,
        threshold,
      });
    };
    handleScroll();
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, [threshold, viewportRef]);

  useEffect(() => cancelScheduledScroll, [cancelScheduledScroll]);

  return { scrollToBottom, resetAutoFollow, isFollowingOutput };
}
