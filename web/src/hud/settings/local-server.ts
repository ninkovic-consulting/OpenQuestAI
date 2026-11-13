// The local model on a server of its own (LM Studio, Ollama and the like):
// its address with a Test that lists the server's models or says what failed,
// the model's name there, and Use this server.

import type { SettingsApi } from "../../net/settings-api";
import { el } from "../dom";
import { button, fieldRow, statusLine } from "./fields";

/** `saved` is the server and model now chosen; `use` saves a choice and answers why it was refused, or null. */
export function serverForm(api: SettingsApi, saved: { backend: string; server: string; model: string }, use: (server: string, model: string) => Promise<string | null>): HTMLElement {
  const root = el("div", "lm-server");
  const address = el("input");
  address.value = saved.server;
  address.placeholder = "http://127.0.0.1:1234/v1";
  address.autocomplete = "off";
  address.spellcheck = false;
  const name = el("input");
  name.value = saved.backend === "openai" ? saved.model : "";
  name.placeholder = "the model's name on the server";
  name.autocomplete = "off";
  name.spellcheck = false;

  const test = button("Test");
  const tested = el("div", "lm-tested");
  tested.setAttribute("role", "status");
  const found = (models: readonly string[]): HTMLElement => {
    const list = el("div", "lm-found");
    for (const m of models) {
      const pick = el("button", "lm-pick", m);
      pick.type = "button";
      pick.addEventListener("click", () => (name.value = m));
      list.append(pick);
    }
    return list;
  };
  test.addEventListener("click", () => {
    test.disabled = true;
    tested.replaceChildren(statusLine("idle", "Asking the server…"));
    void api.testServer(address.value.trim()).then((r) => {
      test.disabled = false;
      if (!r.ok) return tested.replaceChildren(statusLine("bad", r.message));
      const { ok, models, message } = r.value;
      if (!ok) return tested.replaceChildren(statusLine("bad", message));
      const count = models.length === 1 ? "1 model" : `${models.length} models`;
      tested.replaceChildren(statusLine("ok", models.length === 0 ? "The server answers but lists no models." : `The server answers and has ${count}. Choose one to use its name:`), ...(models.length > 0 ? [found(models)] : []));
    });
  });

  const addressRow = el("div", "lm-address");
  addressRow.append(address, test);
  const said = el("p", "field-error");
  said.hidden = true;
  const save = button("Use this server", "primary");
  save.addEventListener("click", () => {
    save.disabled = true;
    said.hidden = true;
    void use(address.value.trim(), name.value.trim()).then((problem) => {
      save.disabled = false;
      said.hidden = problem === null;
      said.textContent = problem ?? "";
    });
  });
  const actions = el("div", "row-actions");
  actions.append(save);
  root.append(
    fieldRow("Server address", addressRow, { note: "An http:// or https:// address on this Mac, like LM Studio's http://127.0.0.1:1234/v1 or Ollama's http://127.0.0.1:11434/v1." }),
    tested,
    fieldRow("Model name", name, { note: "As the server calls it. Offline mode needs the server running and the model loaded." }),
    actions,
    said,
  );
  return root;
}
