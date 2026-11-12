/** Create an element with classes and optional text. */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className = "",
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Set text only when it changed, so frequent renders stay cheap. */
export function setText(node: Node, text: string): void {
  if (node.textContent !== text) node.textContent = text;
}
