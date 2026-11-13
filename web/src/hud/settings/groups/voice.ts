import type { SpeakChoice, VoiceDevices, VoiceState } from "../../../net/settings-types";
import { el } from "../../dom";
import { row, selectInput, textInput, type Choice } from "../bind";
import type { Group, SettingsContext } from "../context";
import { downloadControl } from "../download-control";
import { block, button, note, statusLine } from "../fields";
import { voiceLabel } from "../format";
import { micPermission, silentMic, voiceTest } from "../voice-parts";

const NOT_CONNECTED = "Not connected: the system default is used until it is back.";

export const voiceGroup: Group = {
  id: "voice",
  title: "Voice",
  blurb: "Talking out loud: the microphone, the speakers, the speaking voice. Device and voice changes apply at once.",
  prefixes: ["voice."],
  render(ctx) {
    const v = ctx.settings.voice;
    const root = el("div", "group-body");
    if (!v.installed) {
      root.append(statusLine("bad", "Voice is not installed. Run `uv sync --extra voice` in the project folder, then restart the assistant."));
      return root;
    }
    const devices = deviceList(ctx);
    root.append(
      block("Voice", onOff(ctx, v, () => devices.focusMic())),
      block("Microphone permission", micPermission(ctx.native, v)),
      block("Devices and voice", devices.root),
      block("Speech models", downloadControl(ctx.api, "speech_models", () => void modelsArrived(ctx, v))),
      block("Microphone test", el("p", "field-note", "Records three seconds, writes down what it heard and says a sentence back."), voiceTest(ctx.api)),
    );
    return root;
  },
};

function onOff(ctx: SettingsContext, v: VoiceState, chooseMic: () => void): HTMLElement {
  const root = el("div", "on-off");
  const result = note(v.enabled ? "" : "Turning voice on opens the microphone.");
  /** Try again: open the microphone loop anew, voice staying on. */
  const turnOn = (): Promise<void> =>
    ctx.api.setVoice(true).then((r) => {
      if (r.ok) ctx.adopt({ ...ctx.settings, voice: r.value });
      else result.textContent = r.message;
    });
  if (v.enabled && !v.running && v.mic === "silent") {
    const flip = button("Turn voice off");
    flip.addEventListener("click", () => switchVoice(ctx, false, flip, result));
    root.append(silentMic(ctx.native, v, turnOn, chooseMic), flip, result);
    return root;
  }
  if (v.enabled && !v.running && !v.models_downloaded) {
    const flip = button("Turn voice off");
    flip.addEventListener("click", () => switchVoice(ctx, false, flip, result));
    root.append(statusLine("warn", "On, but the speech models are not downloaded. Download them under Speech models below; nothing downloads by itself."), flip, result);
    return root;
  }
  const line = v.running
    ? statusLine("ok", "On. The assistant is listening for you.")
    : v.enabled
      ? statusLine("warn", `On, but the microphone loop is not running.${v.mic_detail ? ` ${v.mic_detail}` : ""}`)
      : statusLine("idle", "Off. You can still type to the assistant: press /.");
  const flip = button(v.enabled ? "Turn voice off" : "Turn voice on", v.enabled ? "plain" : "primary");
  flip.addEventListener("click", () => switchVoice(ctx, !v.enabled, flip, result));
  root.append(line, flip, result);
  return root;
}

/**
 * The speech models finished downloading. With voice on but stopped for want of
 * them, start it now: the owner asked for voice and for the models.
 */
async function modelsArrived(ctx: SettingsContext, v: VoiceState): Promise<void> {
  if (!v.enabled || v.running) return ctx.reload({ redraw: false });
  const r = await ctx.api.setVoice(true);
  if (r.ok) ctx.adopt({ ...ctx.settings, voice: r.value });
  else await ctx.reload();
}

function switchVoice(ctx: SettingsContext, enabled: boolean, flip: HTMLButtonElement, result: HTMLElement): void {
  flip.disabled = true;
  result.textContent = enabled ? "Opening the microphone…" : "Turning voice off…";
  void ctx.api.setVoice(enabled).then((r) => {
    flip.disabled = false;
    if (!r.ok) {
      result.textContent = r.message;
      return;
    }
    ctx.adopt({ ...ctx.settings, voice: r.value });
  });
}

interface DeviceList {
  root: HTMLElement;
  focusMic(): void;
}

/**
 * The device fields with a Refresh button. The list is read again when the
 * group opens, on Refresh, and whenever the window gets focus back (after
 * connecting AirPods in Control Centre, say), so a new device shows at once.
 */
function deviceList(ctx: SettingsContext): DeviceList {
  const root = el("div", "devices");
  const fields = el("div", "device-fields");
  const refresh = button("Refresh");
  const status = note("Listing the devices…");
  const head = el("div", "row-actions devices-head");
  head.append(refresh, status);
  root.append(head, fields);
  let mic: HTMLSelectElement | null = null;
  let busy = false;

  const load = (): void => {
    if (busy) return;
    busy = refresh.disabled = true;
    status.textContent = "Listing the devices…";
    void ctx.api.voiceDevices().then((r) => {
      busy = refresh.disabled = false;
      if (!r.ok) {
        status.textContent = r.message;
        return;
      }
      const built = deviceFields(ctx, r.value);
      mic = built.mic;
      fields.replaceChildren(...built.nodes);
      status.textContent = "";
    });
  };
  const onFocus = (): void => {
    if (!root.isConnected) window.removeEventListener("focus", onFocus);
    else load();
  };
  refresh.addEventListener("click", load);
  window.addEventListener("focus", onFocus);
  load();
  return { root, focusMic: () => mic?.focus() };
}

function deviceFields(ctx: SettingsContext, d: VoiceDevices): { nodes: HTMLElement[]; mic: HTMLSelectElement } {
  /** The choices for a device field, keeping a chosen device that is not connected now. */
  const choices = (field: string, list: VoiceDevices["inputs"]): { choices: Choice[]; missing: boolean } => {
    const fallback = list.find((x) => x.default)?.name;
    const all: Choice[] = [{ value: "", label: fallback ? `System default (${fallback})` : "System default" }, ...list.map((x) => ({ value: x.name, label: x.name }))];
    const chosen = ctx.draft[field] ?? "";
    const missing = chosen !== "" && !list.some((x) => x.name === chosen);
    return { choices: missing ? [...all, { value: chosen, label: `${chosen} (not connected)` }] : all, missing };
  };
  const device = (field: string, label: string, list: VoiceDevices["inputs"]): { node: HTMLElement; select: HTMLSelectElement } => {
    const { choices: options, missing } = choices(field, list);
    const select = selectInput(ctx, field, options);
    return { node: row(ctx, field, label, select, missing ? { note: NOT_CONNECTED } : {}), select };
  };
  const followup = el("div", "unit-input");
  followup.append(textInput(ctx, "voice.followup_s", { inputMode: "decimal" }), el("span", "unit", "seconds"));
  const input = device("voice.input_device", "Microphone", d.inputs);
  const output = device("voice.output_device", "Speakers", d.outputs);
  const pair = el("div", "two-up");
  pair.append(input.node, output.node);
  const pair2 = el("div", "two-up");
  pair2.append(
    row(ctx, "voice.tts_voice", "Speaking voice", selectInput(ctx, "voice.tts_voice", d.voices.map((id) => ({ value: id, label: voiceLabel(id) })))),
    row(ctx, "voice.followup_s", "Follow-up window", followup, { note: "How long it keeps listening after it answers, without Space." }),
  );
  return { nodes: [pair, pair2, speakTest(ctx)], mic: input.select };
}

/** Says one short sentence in the chosen voice through the chosen speakers, saved or not. */
function speakTest(ctx: SettingsContext): HTMLElement {
  const root = el("div", "speak-test");
  const say = button("Say a test sentence");
  const out = el("div", "test-result");
  out.setAttribute("aria-live", "polite");
  const actions = el("div", "row-actions");
  actions.append(say, el("p", "field-note", "Plays one short sentence in the speaking voice through the speakers above. The microphone stays closed."));
  root.append(actions, out);
  say.addEventListener("click", () => {
    say.disabled = true;
    out.replaceChildren(statusLine("warn", "Speaking…"));
    const choice: SpeakChoice = {};
    const voice = ctx.draft["voice.tts_voice"];
    const speakers = ctx.draft["voice.output_device"];
    if (voice !== undefined) choice.tts_voice = voice;
    if (speakers !== undefined) choice.output_device = speakers;
    void ctx.api.speakTest(choice).then((r) => {
      say.disabled = false;
      if (!r.ok) out.replaceChildren(statusLine("bad", r.message));
      else out.replaceChildren(statusLine(r.value.ok ? "ok" : "bad", r.value.message));
    });
  });
  return root;
}
