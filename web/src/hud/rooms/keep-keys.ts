// Space and Enter pressed on a button or in a field of the room card or the
// agents' lists do their own work there: they must not reach the window's
// push to talk. Escape and the other keys go on as usual.

export function keepKeys(root: HTMLElement): void {
  root.addEventListener("keydown", (ev) => {
    if (ev.key === " " || ev.key === "Enter") ev.stopPropagation();
  });
}
