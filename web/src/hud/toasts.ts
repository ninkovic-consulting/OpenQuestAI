// Notices as small toasts, top right. Each fades out on its own; a click dismisses it.

import type { Store, Toast } from "../net/store";
import { el } from "./dom";

const LIFETIME_MS = { info: 5000, warn: 8000, error: 12000 } as const;

export function mountToasts(parent: HTMLElement, store: Store): void {
  const root = el("div", "toasts");
  root.setAttribute("role", "status");
  parent.append(root);
  const shown = new Map<number, HTMLElement>();

  const show = (toast: Toast): void => {
    const node = el("div", `toast ${toast.level}`);
    node.append(el("span", "dot"), el("span", "", toast.text));
    node.addEventListener("click", () => store.dispatch({ kind: "dismiss", id: toast.id }));
    setTimeout(() => store.dispatch({ kind: "dismiss", id: toast.id }), LIFETIME_MS[toast.level]);
    shown.set(toast.id, node);
    root.append(node);
  };

  store.subscribe((s, prev) => {
    if (s.toasts === prev.toasts) return;
    const ids = new Set(s.toasts.map((t) => t.id));
    for (const [id, node] of shown) {
      if (!ids.has(id)) {
        node.remove();
        shown.delete(id);
      }
    }
    for (const t of s.toasts) if (!shown.has(t.id)) show(t);
  });
}
