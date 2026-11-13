// Voice pieces shared by the Voice group and the wizard: the microphone
// permission, the silent microphone and the three-second test.

import type { MicStatus, NativeHelpers } from "../../net/native";
import type { SettingsApi } from "../../net/settings-api";
import type { VoiceState } from "../../net/settings-types";
import { el } from "../dom";
import { button, note, statusLine, type Tone } from "./fields";

const MIC_PATH = "System Settings, Privacy & Security, Microphone";

const NATIVE_WORDS: Record<MicStatus, [Tone, string]> = {
  granted: ["ok", "Allowed. The assistant can hear the microphone."],
  undetermined: ["idle", "Not asked yet. Allow it here; macOS asks you once."],
  denied: ["bad", `Denied. Allow it in ${MIC_PATH}, then come back.`],
  restricted: ["bad", "Restricted by this Mac's management settings; it cannot be allowed from here."],
};

/** What the daemon learnt when it last opened the microphone. */
export function daemonMicLine(voice: VoiceState): HTMLElement {
  switch (voice.mic) {
    case "granted":
      return statusLine("ok", "Allowed. The microphone answered the last time it was opened.");
    case "denied":
      return statusLine("bad", `Denied. Allow it in ${MIC_PATH}, then turn voice on again.${voice.mic_detail ? ` (${voice.mic_detail})` : ""}`);
    case "silent":
      return statusLine("idle", "Not known: the microphone opened but sent only silence, which is usually the device, not the permission.");
    case "unknown":
      return statusLine("idle", "Not known yet: it shows once voice is turned on or tested.");
  }
}

/**
 * The chosen microphone opened but sent only zeros. That is nearly always the
 * device (muted, asleep, covered, a closed laptop lid), so it leads; the
 * permission is mentioned only when the app cannot say it is allowed.
 */
export function silentMic(native: NativeHelpers, voice: VoiceState, again: () => Promise<void>, choose: () => void): HTMLElement {
  const root = el("div", "silent-mic");
  const who = voice.input_device ? `the microphone “${voice.input_device}”` : "the system default microphone";
  const permission = note("");
  const status = native.micStatus;
  const permissionLine = `If no microphone works, check that the assistant may use it in ${MIC_PATH}.`;
  if (status) void status().then((mic) => (permission.textContent = mic === "granted" ? "" : permissionLine));
  else permission.textContent = permissionLine;
  const retry = button("Try again", "primary");
  const pick = button("Choose another microphone");
  retry.addEventListener("click", () => {
    retry.disabled = true;
    retry.textContent = "Opening the microphone…";
    void again();
  });
  pick.addEventListener("click", choose);
  const actions = el("div", "row-actions");
  actions.append(retry, pick);
  root.append(
    statusLine("warn", `On, but ${who} sends only silence. It may be muted, asleep or covered: a webcam in privacy mode, or a laptop's own microphone with the lid closed.`),
    permission,
    actions,
  );
  return root;
}

/**
 * The microphone permission: with the app's helpers, its live status, an
 * Allow button and a way to System Settings; without them, what the daemon saw.
 */
export function micPermission(native: NativeHelpers, voice: VoiceState): HTMLElement {
  const root = el("div", "mic-permission");
  const status = native.micStatus;
  if (!status) {
    root.append(daemonMicLine(voice));
    return root;
  }
  const draw = (mic: MicStatus): void => {
    const [tone, text] = NATIVE_WORDS[mic];
    const actions = el("div", "row-actions");
    const request = native.requestMic;
    if (mic === "undetermined" && request) {
      const allow = button("Allow microphone", "primary");
      allow.addEventListener("click", () => {
        allow.disabled = true;
        void request().then(draw);
      });
      actions.append(allow);
    }
    const open = native.openSystemSettings;
    if ((mic === "denied" || mic === "restricted") && open) {
      const go = button("Open System Settings");
      go.addEventListener("click", () => void open("microphone"));
      const again = button("Check again");
      again.addEventListener("click", () => void status().then(draw));
      actions.append(go, again);
    }
    root.replaceChildren(statusLine(tone, text), actions);
  };
  root.append(statusLine("idle", "Checking…"));
  void status().then(draw);
  return root;
}

/** A button that records three seconds and shows what was heard. */
export function voiceTest(api: SettingsApi, onDone: (ok: boolean) => void = () => {}): HTMLElement {
  const root = el("div", "voice-test");
  const start = button("Test for three seconds", "primary");
  const out = el("div", "test-result");
  out.setAttribute("aria-live", "polite");
  root.append(start, out);
  start.addEventListener("click", () => {
    start.disabled = true;
    out.replaceChildren(statusLine("warn", "Listening for three seconds… say something."));
    void api.voiceTest().then((r) => {
      start.disabled = false;
      if (!r.ok) {
        out.replaceChildren(statusLine("bad", r.message));
        onDone(false);
        return;
      }
      const t = r.value;
      out.replaceChildren(t.ok ? heard(t.heard) : statusLine("bad", t.message));
      onDone(t.ok);
    });
  });
  return root;
}

function heard(text: string): HTMLElement {
  const node = el("figure", "heard");
  node.append(el("figcaption", "caps", "Heard"), el("blockquote", "", text));
  return node;
}
