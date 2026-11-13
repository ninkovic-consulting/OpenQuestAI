import { describe, expect, it } from "vitest";

import { initialState, reduce } from "../net/store";
import { asListenView, asOutbound, type ListenView } from "../net/types";
import { fieldPrompt, headsetWarning, MODE_LINES, needsConfirm, quickControl, talkHint, talkLabel } from "./listen";

const view = (over: Partial<ListenView> = {}): ListenView => ({
  mode: "hold",
  mic: "closed",
  voice: true,
  listening: "wake",
  shell_free: false,
  ...over,
});

describe("the key hint", () => {
  it("says what Space does in each mode, with the real name", () => {
    expect(talkHint("hold", "Juniper")).toBe("Hold Space to talk");
    expect(talkHint("wake", "Juniper")).toBe("Say Juniper, or hold Space");
    expect(talkHint("always", "Juniper")).toBe("Listening");
  });
});

describe("the hold-to-talk control", () => {
  it("says opening the microphone until audio arrives, then listening", () => {
    expect(talkLabel(view({ mic: "opening" }), true, "Vision")).toBe("Opening the microphone");
    expect(talkLabel(view({ mic: "open" }), true, "Vision")).toBe("Listening");
  });

  it("says what the mode asks while nothing is held", () => {
    expect(talkLabel(view(), false, "Vision")).toBe("Hold to talk");
    expect(talkLabel(view({ mode: "wake", mic: "open" }), false, "Vision")).toBe("Say Vision or hold");
    expect(talkLabel(view({ mode: "always", mic: "open" }), false, "Vision")).toBe("Listening");
    expect(talkLabel(null, false, "Vision")).toBe("Hold to talk");
  });

  it("keeps to a few words in the widget", () => {
    expect(talkLabel(view({ mode: "wake", mic: "open" }), false, "Vision", true)).toBe("Hold to talk");
    expect(talkLabel(view({ mic: "opening" }), true, "Vision", true)).toBe("Opening");
    expect(fieldPrompt(view({ mode: "wake" }), "Vision", true)).toBe("Write, or say Vision");
    expect(fieldPrompt(view(), "Vision", true)).toBe("Write to Vision");
  });

  it("gives the field a prompt for the mode", () => {
    expect(fieldPrompt(view(), "Vision")).toBe("Write to Vision, or hold Space to talk");
    expect(fieldPrompt(view({ mode: "wake" }), "Vision")).toBe("Write to Vision, or say Vision");
    expect(fieldPrompt(view({ mode: "always" }), "")).toBe("Write a message, or just talk");
  });
});

describe("the quick control", () => {
  it("is hidden until the daemon says how it listens", () => {
    expect(quickControl(null, "Vision").shown).toBe(false);
  });

  it("goes from hold to the listening mode last chosen, and back", () => {
    expect(quickControl(view(), "Vision")).toMatchObject({ label: "Hold to talk", next: "wake", listening: false, mic: false });
    expect(quickControl(view({ listening: "always" }), "Vision").next).toBe("always");
    expect(quickControl(view({ mode: "always", mic: "open", listening: "always" }), "Vision")).toMatchObject({ label: "Always", next: "hold", listening: true, mic: true });
    expect(quickControl(view({ mode: "wake", mic: "open" }), "Vision").label).toBe("Wake word");
  });

  it("marks the microphone in hold only while a stream is open", () => {
    expect(quickControl(view({ mic: "closed" }), "Vision").mic).toBe(false);
    expect(quickControl(view({ mic: "opening" }), "Vision").mic).toBe(true);
    expect(quickControl(view({ mic: "open" }), "Vision").mic).toBe(true);
  });

  it("is off while voice is off", () => {
    const q = quickControl(view({ voice: false, mic: "open" }), "Vision");
    expect(q).toMatchObject({ disabled: true, label: "Voice off", mic: false });
  });

  it("asks first only for always with a free shell", () => {
    expect(needsConfirm("always", true)).toBe(true);
    expect(needsConfirm("always", false)).toBe(false);
    expect(needsConfirm("wake", true)).toBe(false);
  });

  it("says what each mode does to the microphone", () => {
    expect(MODE_LINES.hold).toMatch(/closed until you hold/);
    expect(MODE_LINES.always).toMatch(/stays open/);
  });
});

describe("the listen state", () => {
  it("comes from the snapshot and then from voice.listen", () => {
    const listen = view({ mode: "wake", mic: "open" });
    let s = reduce(initialState(), {
      kind: "snapshot",
      snapshot: { state: "idle", brain: "claude", gate_pending: [], notices: [], budget: { month: "2026-11", spent_usd: 0, cap_usd: 10 }, listen },
      initial: true,
    });
    expect(s.listen).toEqual(listen);
    const event = asOutbound({ type: "voice.listen", ts: 1, data: view({ mic: "opening" }) });
    expect(event).not.toBeNull();
    if (event) s = reduce(s, { kind: "event", event });
    expect(s.listen?.mic).toBe("opening");
  });

  it("refuses a shape it does not know", () => {
    expect(asListenView({ ...view(), mode: "sometimes" })).toBeNull();
    expect(asListenView({ ...view(), mic: "on" })).toBeNull();
    expect(asOutbound({ type: "voice.listen", ts: 1, data: { mode: "hold" } })).toBeNull();
  });
});

describe("the Bluetooth headset line", () => {
  const airpods = { name: "AirPods", default: false, bluetooth: true };
  const inputs = [{ name: "MacBook Pro Microphone", default: true }, airpods];
  const outputs = [{ name: "MacBook Pro Speakers", default: true }, airpods];

  it("shows when one headset is both ends and the microphone stays open", () => {
    expect(headsetWarning("wake", inputs, outputs, "AirPods", "AirPods")).toBe(true);
    expect(headsetWarning("always", inputs, outputs, "AirPods", "AirPods")).toBe(true);
  });

  it("does not show in hold, or with another microphone or the built-in pair", () => {
    expect(headsetWarning("hold", inputs, outputs, "AirPods", "AirPods")).toBe(false);
    expect(headsetWarning("wake", inputs, outputs, "", "AirPods")).toBe(false);
    expect(headsetWarning("wake", inputs, outputs, "", "")).toBe(false);
  });

  it("follows the system default when that is the headset", () => {
    const viaDefault = [{ ...airpods, default: true }];
    expect(headsetWarning("wake", viaDefault, viaDefault, "", "")).toBe(true);
  });
});
