import type { VoiceDevices, VoiceState } from "../../../net/settings-types";
import { el } from "../../dom";
import { row, selectInput, textInput, type Choice } from "../bind";
import type { Group, SettingsContext } from "../context";
import { downloadControl } from "../download-control";
import { block, button, note, statusLine } from "../fields";
import { voiceLabel } from "../format";
import { micPermission, voiceTest } from "../voice-parts";

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
    const devices = el("div", "devices");
    devices.append(note("Listing the devices…"));
    void ctx.api.voiceDevices().then((r) => devices.replaceChildren(...(r.ok ? deviceFields(ctx, r.value) : [statusLine("bad", r.message)])));

    root.append(
      block("Voice", onOff(ctx, v)),
      block("Microphone permission", micPermission(ctx.native, v)),
      block("Devices and voice", devices),
      block("Speech models", downloadControl(ctx.api, "speech_models", () => void ctx.reload({ redraw: false }))),
      block("Test", el("p", "field-note", "Records three seconds, writes down what it heard and says a sentence back."), voiceTest(ctx.api)),
    );
    return root;
  },
};

function onOff(ctx: SettingsContext, v: VoiceState): HTMLElement {
  const root = el("div", "on-off");
  const line = v.running
    ? statusLine("ok", "On. The assistant is listening for you.")
    : v.enabled
      ? statusLine("warn", `On, but the microphone loop is not running.${v.mic_detail ? ` ${v.mic_detail}` : ""}`)
      : statusLine("idle", "Off. You can still type to the assistant: press /.");
  const flip = button(v.enabled ? "Turn voice off" : "Turn voice on", v.enabled ? "plain" : "primary");
  const result = note(v.enabled ? "" : "Turning voice on opens the microphone.");
  flip.addEventListener("click", () => {
    flip.disabled = true;
    result.textContent = v.enabled ? "Turning voice off…" : "Opening the microphone…";
    void ctx.api.setVoice(!v.enabled).then((r) => {
      flip.disabled = false;
      if (!r.ok) {
        result.textContent = r.message;
        return;
      }
      ctx.adopt({ ...ctx.settings, voice: r.value });
    });
  });
  root.append(line, flip, result);
  return root;
}

function deviceFields(ctx: SettingsContext, d: VoiceDevices): HTMLElement[] {
  const choices = (list: VoiceDevices["inputs"]): Choice[] => {
    const fallback = list.find((x) => x.default)?.name;
    return [{ value: "", label: fallback ? `System default (${fallback})` : "System default" }, ...list.map((x) => ({ value: x.name, label: x.name }))];
  };
  const followup = el("div", "unit-input");
  followup.append(textInput(ctx, "voice.followup_s", { inputMode: "decimal" }), el("span", "unit", "seconds"));
  const pair = el("div", "two-up");
  pair.append(
    row(ctx, "voice.input_device", "Microphone", selectInput(ctx, "voice.input_device", choices(d.inputs))),
    row(ctx, "voice.output_device", "Speakers", selectInput(ctx, "voice.output_device", choices(d.outputs))),
  );
  const pair2 = el("div", "two-up");
  pair2.append(
    row(ctx, "voice.tts_voice", "Speaking voice", selectInput(ctx, "voice.tts_voice", d.voices.map((id) => ({ value: id, label: voiceLabel(id) })))),
    row(ctx, "voice.followup_s", "Follow-up window", followup, { note: "How long it keeps listening after it answers, without Space." }),
  );
  return [pair, pair2];
}
