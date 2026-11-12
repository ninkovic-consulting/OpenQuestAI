// The API key: where it is, a write-only field to replace it, and a check.
// The key is sent once in a POST body, the field is emptied at once, and the
// key is never shown, logged or kept here.

import type { SettingsApi } from "../../net/settings-api";
import type { KeyAnswer, Settings, Verdict } from "../../net/settings-types";
import { el } from "../dom";
import { button, fieldRow, statusLine, type Tone } from "./fields";
import { keySourceWords, verdictWords } from "./format";

const VERDICT_TONE: Record<Verdict, Tone> = { accepted: "ok", refused: "bad", unreachable: "warn", none: "idle" };

export function keyStatus(key: Settings["key"]): HTMLElement {
  return statusLine(key.stored ? "ok" : "bad", keySourceWords(key.source));
}

/** The field and its two buttons; `onStored` hears every answer to a stored key. */
export function keyForm(api: SettingsApi, stored: boolean, onStored: (answer: KeyAnswer) => void): HTMLElement {
  const root = el("div", "key-form");
  const input = el("input");
  input.type = "password";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = "sk-ant-…";
  const save = button(stored ? "Replace key" : "Save key", "primary");
  const verify = button("Verify");
  verify.hidden = !stored;
  const result = el("div", "key-result");
  result.setAttribute("aria-live", "polite");
  const show = (tone: Tone, text: string): void => {
    result.replaceChildren(statusLine(tone, text));
  };

  const send = (): void => {
    const key = input.value.trim();
    input.value = "";
    if (!key) {
      show("bad", "Paste the key first.");
      return;
    }
    save.disabled = true;
    show("warn", "Storing the key and checking it…");
    void api.storeKey(key).then((r) => {
      save.disabled = false;
      if (!r.ok) {
        show("bad", r.message);
        return;
      }
      verify.hidden = false;
      show(VERDICT_TONE[r.value.verdict], `Stored. ${verdictWords(r.value.verdict)}`);
      onStored(r.value);
    });
  };
  save.addEventListener("click", send);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") send();
  });
  verify.addEventListener("click", () => {
    verify.disabled = true;
    show("warn", "Checking the key with Anthropic…");
    void api.verifyKey().then((r) => {
      verify.disabled = false;
      if (r.ok) show(VERDICT_TONE[r.value], verdictWords(r.value));
      else show("bad", r.message);
    });
  });
  const actions = el("div", "row-actions");
  actions.append(save, verify);
  root.append(
    fieldRow(stored ? "New key" : "API key", input, { note: "From console.anthropic.com, Settings, API keys. It goes to the Keychain and is never shown again." }),
    actions,
    result,
  );
  return root;
}
