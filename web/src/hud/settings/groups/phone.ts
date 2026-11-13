import type { PhoneApi } from "../../../net/phone-api";
import type { PhoneNotify, PhonePatch, PhoneView } from "../../../net/phone-types";
import { el, setText } from "../../dom";
import type { Group } from "../context";
import { block, button, confirmButton, fieldRow, note, statusLine } from "../fields";
import { formatWhen } from "../format";
import { codeLine, connectionLine, pairedLine, spacedCode, toggledTools, verdictLine, voiceNotesLine } from "../phone-parts";

const POLL_MS = 2000;

export const phoneGroup: Group = {
  id: "phone",
  title: "Phone",
  blurb: "Message the assistant from your phone through a Discord bot of your own. Only the paired account is answered; changes apply at once.",
  prefixes: [],
  render(ctx) {
    const api = ctx.phone;
    const root = el("div", "group-body phone");
    const said = note();
    let view: PhoneView | null = null;
    let timer = 0;

    const apply = (next: PhoneView): void => {
      view = next;
      draw();
    };
    const change = (patch: PhonePatch, done: string): void => {
      void api.update(patch).then((r) => {
        setText(said, r.ok ? done : r.message);
        if (r.ok) apply(r.value);
      });
    };

    const draw = (): void => {
      if (!view) {
        root.replaceChildren(statusLine("idle", "Loading the phone channel…"));
        return;
      }
      const v = view;
      root.replaceChildren(
        block("Channel", channelBlock(v, change)),
        block("Bot token", tokenForm(api, v, (text) => {
          setText(said, text);
          void load();
        })),
        block("Pairing", pairingBlock(api, v, apply, () => void load())),
        block("Send to the phone", notifyChoices(v, change)),
        block("Replies", replyChoices(v, change)),
        block("Approvals from the phone", toolChoices(v, change)),
        block("Voice notes", statusLine(voiceNotesLine(v).tone, voiceNotesLine(v).text)),
        said,
      );
    };

    const load = async (): Promise<void> => {
      const r = await api.view();
      if (!r.ok) {
        root.replaceChildren(statusLine("bad", `The phone channel could not be loaded: ${r.message}`));
        return;
      }
      apply(r.value);
    };

    // While a code is shown, look for the pairing every two seconds; stop once this group is gone.
    const poll = (): void => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (!root.isConnected) return;
        if (view?.pairing || view?.connection === "connecting") void load().then(poll);
        else poll();
      }, POLL_MS);
    };
    draw();
    void load().then(poll);
    return root;
  },
};

type Change = (patch: PhonePatch, done: string) => void;

function channelBlock(v: PhoneView, change: Change): HTMLElement {
  const root = el("div", "on-off");
  const line = connectionLine(v);
  const flip = button(v.enabled ? "Turn the channel off" : "Turn the channel on", v.enabled ? "plain" : "primary");
  flip.addEventListener("click", () => {
    flip.disabled = true;
    change({ enabled: !v.enabled }, v.enabled ? "The phone channel is off." : "The phone channel is on.");
  });
  root.append(statusLine(line.tone, line.text), flip);
  return root;
}

function tokenForm(api: PhoneApi, v: PhoneView, stored: (text: string) => void): HTMLElement {
  const root = el("div", "key-form");
  const input = el("input");
  input.type = "password";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = v.token.stored ? "Stored; paste a new one to replace it" : "Paste the bot token";
  const save = button(v.token.stored ? "Replace token" : "Save token", "primary");
  const verify = button("Verify");
  verify.hidden = !v.token.stored;
  const result = el("div", "key-result");
  result.setAttribute("aria-live", "polite");
  const show = (tone: Parameters<typeof statusLine>[0], text: string): void => {
    result.replaceChildren(statusLine(tone, text));
  };
  const send = (): void => {
    const token = input.value.trim();
    input.value = "";
    if (!token) {
      show("bad", "Paste the token first.");
      return;
    }
    save.disabled = true;
    show("warn", "Checking the token with Discord…");
    void api.storeToken(token).then((r) => {
      save.disabled = false;
      if (!r.ok) {
        show("bad", r.message);
        return;
      }
      const line = verdictLine(r.value.verdict, r.value.bot);
      stored(`Stored in the Keychain. ${line.text}`);
    });
  };
  save.addEventListener("click", send);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") send();
  });
  verify.addEventListener("click", () => {
    verify.disabled = true;
    show("warn", "Asking Discord who the bot is…");
    void api.verifyToken().then((r) => {
      verify.disabled = false;
      if (!r.ok) show("bad", r.message);
      else show(verdictLine(r.value.verdict, r.value.bot).tone, verdictLine(r.value.verdict, r.value.bot).text);
    });
  });
  const actions = el("div", "row-actions");
  actions.append(save, verify);
  root.append(
    fieldRow(v.token.stored ? "New token" : "Bot token", input, {
      note: "From the Discord Developer Portal: your application, Bot, Reset Token. It goes to the Keychain and is never shown again.",
    }),
    actions,
    result,
  );
  return root;
}

function pairingBlock(api: PhoneApi, v: PhoneView, apply: (v: PhoneView) => void, reload: () => void): HTMLElement {
  const root = el("div", "pairing");
  const line = pairedLine(v, formatWhen);
  root.append(statusLine(line.tone, line.text));
  if (v.paired) {
    root.append(
      confirmButton("Unpair", { question: "Unpair the phone? The bot then answers nobody until you pair again.", confirm: "Unpair", danger: true }, async () => {
        const r = await api.unpair();
        if (!r.ok) return r.message;
        apply(r.value);
        return "Unpaired.";
      }),
    );
    return root;
  }
  const said = note();
  if (v.pairing) {
    const words = codeLine(v.pairing, Date.now() / 1000);
    if (words) root.append(el("p", "pairing-code", spacedCode(v.pairing.code)), el("p", "field-note", words));
  }
  const issue = button(v.pairing ? "New code" : "Show a pairing code", v.pairing ? "plain" : "primary");
  issue.disabled = !v.token.stored;
  if (!v.token.stored) said.textContent = "Store the bot token first.";
  issue.addEventListener("click", () => {
    issue.disabled = true;
    void api.newCode().then((r) => {
      if (!r.ok) {
        issue.disabled = false;
        setText(said, r.message);
        return;
      }
      reload();
    });
  });
  root.append(issue, said);
  return root;
}

function checkbox(label: string, checked: boolean, onChange: (on: boolean) => void): HTMLElement {
  const choice = el("label", "check-choice");
  const input = el("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  choice.append(input, el("span", "", label));
  return choice;
}

function notifyChoices(v: PhoneView, change: Change): HTMLElement {
  const root = el("div", "choices");
  const one = (key: keyof PhoneNotify, label: string): HTMLElement =>
    checkbox(label, v.notify[key], (on) => change({ notify: { [key]: on } }, on ? `${label}: sent to the phone.` : `${label}: not sent.`));
  root.append(
    one("automations", "Automation results"),
    one("warnings", "Warnings and errors"),
    one("approvals", "Requests that need your yes"),
    one("jobs", "Results of jobs you handed off from the phone"),
  );
  return root;
}

function replyChoices(v: PhoneView, change: Change): HTMLElement {
  const root = el("div", "choices");
  root.append(
    checkbox("Also speak replies to the phone on the Mac", v.speak_on_mac, (on) => change({ speak_on_mac: on }, on ? "Replies to the phone are spoken on the Mac too." : "Replies to the phone stay silent on the Mac.")),
    checkbox("Answer a voice note with a voice note too", v.voice_replies, (on) => change({ voice_replies: on }, on ? "Voice notes get a voice reply as well as text." : "Voice notes get a text reply.")),
  );
  return root;
}

function toolChoices(v: PhoneView, change: Change): HTMLElement {
  const root = el("div", "phone-tools");
  root.append(el("p", "field-note", "A request for one of these can be approved with Yes on the phone. The rest wait for you at the Mac."));
  const list = el("div", "tool-list");
  for (const t of v.tools) {
    const macOnly = v.mac_only.includes(t.id);
    const on = !macOnly && v.phone_tools.includes(t.id);
    const b = el("button", `tool-toggle${macOnly ? " is-unavailable" : ""}`);
    b.type = "button";
    b.setAttribute("aria-pressed", String(on));
    b.append(el("span", "dot"), el("span", "", t.title));
    if (macOnly) {
      b.disabled = true;
      b.title = `${t.title} is only ever approved at the Mac.`;
      b.append(el("span", "tag", "at the Mac"));
    } else {
      b.addEventListener("click", () => change({ phone_tools: toggledTools(v, t.id) }, on ? `${t.title} now waits for the Mac.` : `${t.title} can be approved from the phone.`));
    }
    list.append(b);
  }
  root.append(list);
  return root;
}
