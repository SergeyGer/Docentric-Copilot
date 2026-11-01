/** Browser helpers that must not run during server rendering. */

export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Clipboard permissions can be denied outside a user gesture; fall back.
    }
  }
  if (typeof document === "undefined") {
    return false;
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const succeeded = document.execCommand("copy");
    area.remove();
    return succeeded;
  } catch {
    return false;
  }
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function scrollToElement(elementId: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const element = document.getElementById(elementId);
  if (!element) {
    return;
  }
  element.scrollIntoView({
    behavior: prefersReducedMotion() ? "auto" : "smooth",
    block: "start",
  });
}

export function focusElement(elementId: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const element = document.getElementById(elementId);
  if (element instanceof HTMLElement) {
    element.focus({ preventScroll: true });
  }
}
