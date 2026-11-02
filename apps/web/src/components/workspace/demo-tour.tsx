"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { ArrowLeft, ArrowRight, Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { prefersReducedMotion } from "@/lib/clipboard";
import type { DemoTourStep } from "@/lib/types";

interface SpotlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface Viewport {
  width: number;
  height: number;
}

const CARD_WIDTH = 360;
const VIEWPORT_MARGIN = 16;
const SPOTLIGHT_PADDING = 8;

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface DemoTourProps {
  steps: DemoTourStep[];
  onClose: () => void;
}

/**
 * Spotlight tour driven by the demo response. The page underneath stays
 * readable through the spotlight; the dimming is a large box shadow around the
 * highlighted section. All actions are reachable by keyboard and Esc closes.
 */
export function DemoTour({ steps, onClose }: DemoTourProps) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<SpotlightRect | null>(null);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  const [cardHeight, setCardHeight] = useState(240);
  const cardRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  const step = steps[index] ?? null;
  const lastStep = index >= steps.length - 1;

  useEffect(() => {
    setIndex(0);
  }, [steps]);

  const measure = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const nextViewport = { width: window.innerWidth, height: window.innerHeight };
    setViewport((previous) =>
      previous &&
      previous.width === nextViewport.width &&
      previous.height === nextViewport.height
        ? previous
        : nextViewport,
    );
    if (!step) {
      setRect(null);
      return;
    }
    let target: Element | null = null;
    try {
      target = document.querySelector(step.target);
    } catch {
      target = null;
    }
    if (!(target instanceof HTMLElement)) {
      setRect(null);
      return;
    }
    const box = target.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) {
      setRect(null);
      return;
    }
    const nextRect = {
      top: box.top,
      left: box.left,
      width: box.width,
      height: box.height,
    };
    setRect((previous) =>
      previous &&
      Math.abs(previous.top - nextRect.top) < 0.5 &&
      Math.abs(previous.left - nextRect.left) < 0.5 &&
      Math.abs(previous.width - nextRect.width) < 0.5 &&
      Math.abs(previous.height - nextRect.height) < 0.5
        ? previous
        : nextRect,
    );
  }, [step]);

  // Scroll the highlighted panel into view, then keep the spotlight in sync.
  useEffect(() => {
    if (!step || typeof window === "undefined") {
      return;
    }
    let target: Element | null = null;
    try {
      target = document.querySelector(step.target);
    } catch {
      target = null;
    }
    if (target instanceof HTMLElement) {
      target.scrollIntoView({
        behavior: prefersReducedMotion() ? "auto" : "smooth",
        block: "center",
        inline: "nearest",
      });
    }
    measure();
    const frame = window.requestAnimationFrame(measure);
    return () => window.cancelAnimationFrame(frame);
  }, [measure, step]);

  useEffect(() => {
    const update = () => measure();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(update);
      observer.observe(document.body);
      let target: Element | null = null;
      try {
        target = document.querySelector(step?.target ?? "");
      } catch {
        target = null;
      }
      if (target instanceof HTMLElement) {
        observer.observe(target);
      }
    }
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
      observer?.disconnect();
    };
  }, [measure, step?.target]);

  useEffect(() => {
    if (cardRef.current) {
      setCardHeight(cardRef.current.offsetHeight);
    }
  }, [index, step, viewport?.width]);

  useEffect(() => {
    previousFocus.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => cardRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      previousFocus.current?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const card = cardRef.current;
      if (!card) {
        return;
      }
      const focusable = Array.from(card.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) {
        event.preventDefault();
        card.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!step) {
    return null;
  }

  const cardWidth =
    viewport === null ? CARD_WIDTH : Math.min(CARD_WIDTH, viewport.width - VIEWPORT_MARGIN * 2);
  let cardStyle: CSSProperties;
  if (!rect || !viewport) {
    cardStyle = {
      left: "50%",
      top: "50%",
      transform: "translate(-50%, -50%)",
      width: `min(${CARD_WIDTH}px, calc(100vw - 2rem))`,
    };
  } else {
    const gap = 14;
    let top = rect.top + rect.height + gap;
    if (top + cardHeight > viewport.height - VIEWPORT_MARGIN) {
      top = rect.top - cardHeight - gap;
    }
    top = Math.max(
      VIEWPORT_MARGIN,
      Math.min(top, viewport.height - cardHeight - VIEWPORT_MARGIN),
    );
    const left = Math.max(
      VIEWPORT_MARGIN,
      Math.min(
        rect.left + rect.width / 2 - cardWidth / 2,
        viewport.width - cardWidth - VIEWPORT_MARGIN,
      ),
    );
    cardStyle = { left, top, width: cardWidth, transform: "none" };
  }

  const spotlightStyle =
    rect && viewport
      ? {
          left: Math.max(0, rect.left - SPOTLIGHT_PADDING),
          top: Math.max(0, rect.top - SPOTLIGHT_PADDING),
          width: Math.max(
            1,
            Math.min(
              viewport.width - Math.max(0, rect.left - SPOTLIGHT_PADDING),
              rect.width + SPOTLIGHT_PADDING * 2,
            ),
          ),
          height: Math.max(
            1,
            Math.min(
              viewport.height - Math.max(0, rect.top - SPOTLIGHT_PADDING),
              rect.height + SPOTLIGHT_PADDING * 2,
            ),
          ),
          boxShadow: "0 0 0 9999px rgba(15, 23, 42, 0.68)",
        }
      : undefined;

  return (
    <div className="fixed inset-0 z-[80]">
      <p className="sr-only" aria-live="polite">
        {`Guided tour, step ${index + 1} of ${steps.length}: ${step.title}. ${step.body}`}
      </p>

      {!rect ? (
        <div aria-hidden="true" className="absolute inset-0 bg-slate-950/65" />
      ) : (
        <div aria-hidden="true" className="absolute inset-0" />
      )}

      {spotlightStyle ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute rounded-lg ring-2 ring-primary ring-offset-2 ring-offset-slate-950/70"
          style={spotlightStyle}
        />
      ) : null}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="demo-tour-title"
        aria-describedby="demo-tour-body"
        tabIndex={-1}
        style={cardStyle}
        className="absolute max-h-[calc(100vh-2rem)] overflow-y-auto rounded-xl border border-border bg-card p-4 text-left shadow-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="flex items-start justify-between gap-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
            Guided tour · step {index + 1} of {steps.length}
          </p>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            onClick={onClose}
            aria-label="Close guided tour"
            className="-mr-1 -mt-1 shrink-0 text-muted-foreground hover:text-foreground"
          >
            <X aria-hidden="true" />
          </Button>
        </div>
        <h2
          id="demo-tour-title"
          className="mt-1.5 text-sm font-semibold leading-5 text-foreground"
        >
          {step.title}
        </h2>
        <p id="demo-tour-body" className="mt-1 text-xs leading-5 text-muted-foreground">
          {step.body}
        </p>
        {!rect ? (
          <p className="mt-2 rounded-md border border-warning/30 bg-warning/5 px-2 py-1 text-[11px] text-warning">
            This section is not visible in the current layout. Continue to the next step.
          </p>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <Button type="button" size="sm" variant="ghost" onClick={onClose}>
            Skip tour
          </Button>
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setIndex((current) => Math.max(0, current - 1))}
              disabled={index === 0}
            >
              <ArrowLeft aria-hidden="true" />
              Back
            </Button>
            {lastStep ? (
              <Button type="button" size="sm" onClick={onClose}>
                <Check aria-hidden="true" />
                Finish
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                onClick={() => setIndex((current) => Math.min(steps.length - 1, current + 1))}
              >
                Next
                <ArrowRight aria-hidden="true" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
