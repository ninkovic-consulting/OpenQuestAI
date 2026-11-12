import { describe, expect, it, vi } from "vitest";
import { MockPhone } from "../../net/mock-phone";
import { asPairingCode, asPhoneView, asTokenAnswer } from "../../net/phone-guards";
import type { PhoneView } from "../../net/phone-types";
import { initialState, reduce } from "../../net/store";
import { whoSaid } from "../caption";
import { codeLine, connectionLine, pairedLine, spacedCode, toggledTools, verdictLine, voiceNotesLine } from "./phone-parts";

const TOKEN = "fake-bot-token-for-tests-1.abcdef.fake-bot-token-for-tests-only-1";

async function view(phone: MockPhone): Promise<PhoneView> {
  const r = await phone.view();
  if (!r.ok) throw new Error(r.message);
  return r.value;
}

describe("the phone on the wire", () => {
  it("accepts the daemon's shape and refuses others", async () => {
    const v = await view(new MockPhone(0));
    expect(asPhoneView(v)).not.toBeNull();
    expect(asPhoneView({ ...v, connection: "asleep" })).toBeNull();
    expect(asPhoneView({ ...v, token: { stored: "yes" } })).toBeNull();
    expect(asPhoneView({ ...v, service: "telegram" })).toBeNull();
    expect(asPairingCode({ code: "123456", expires_at: 1 })).not.toBeNull();
    expect(asTokenAnswer({ stored: true, verdict: "accepted", bot: "Vision Bot" })).not.toBeNull();
    expect(asTokenAnswer({ stored: true, verdict: "fine", bot: null })).toBeNull();
  });

  it("never carries the token back", async () => {
    const phone = new MockPhone(0);
    vi.useFakeTimers();
    const stored = phone.storeToken(TOKEN);
    await vi.runAllTimersAsync();
    vi.useRealTimers();
    expect((await stored).ok).toBe(true);
    expect(JSON.stringify(await view(phone))).not.toContain(TOKEN);
  });
});

describe("the mock phone checks like the daemon", () => {
  it("refuses a token that is not shaped like one", async () => {
    const r = await new MockPhone(0).storeToken("sk-ant-not-a-discord-token");
    expect(r.ok).toBe(false);
  });

  it("never lets shell be approved from the phone", async () => {
    const phone = new MockPhone(0);
    const r = await phone.update({ phone_tools: ["shell", "open_url"] });
    expect(r.ok ? "" : r.message).toBe("shell is only ever approved at the Mac.");
    expect((await view(phone)).phone_tools).not.toContain("shell");
  });

  it("pairs once the code is sent, refuses a second code, and unpairs", async () => {
    vi.useFakeTimers();
    const phone = new MockPhone(1000);
    const stored = phone.storeToken(TOKEN);
    await vi.runAllTimersAsync();
    await stored;
    const code = await phone.newCode();
    expect(code.ok && /^\d{6}$/.test(code.value.code)).toBe(true);
    await vi.advanceTimersByTimeAsync(1500);
    vi.useRealTimers();
    const v = await view(phone);
    expect(v.paired?.name).toBe("Owner");
    expect(v.pairing).toBeNull();
    expect((await phone.newCode()).ok).toBe(false);
    const after = await phone.unpair();
    expect(after.ok && after.value.paired).toBeNull();
  });

  it("starts over unpaired, keeping the token unless asked", async () => {
    const phone = new MockPhone(0);
    vi.useFakeTimers();
    const stored = phone.storeToken(TOKEN);
    await vi.runAllTimersAsync();
    vi.useRealTimers();
    await stored;
    await phone.update({ speak_on_mac: true });
    phone.reset(false);
    let v = await view(phone);
    expect(v.token.stored).toBe(true);
    expect(v.speak_on_mac).toBe(false);
    phone.reset(true);
    v = await view(phone);
    expect(v.token.stored).toBe(false);
    expect(v.connection).toBe("no_token");
  });
});

describe("the Phone group's words", () => {
  const base = async (): Promise<PhoneView> => view(new MockPhone(0));

  it("says how the channel stands", async () => {
    const v = await base();
    expect(connectionLine(v)).toEqual({ tone: "idle", text: "Not set up: store the bot token below." });
    expect(connectionLine({ ...v, connection: "online", bot: { name: "Vision Bot" } }).text).toBe("Connected to Discord as Vision Bot.");
    expect(connectionLine({ ...v, connection: "refused", detail: "Discord refused the bot token." }).tone).toBe("bad");
    expect(pairedLine(v, () => "").tone).toBe("idle");
    expect(pairedLine({ ...v, paired: { name: "Owner", since: 0 } }, () => "1 Nov").text).toBe("Paired with Owner since 1 Nov. Only they are answered.");
  });

  it("counts the code down and spaces it", () => {
    const code = { code: "482913", expires_at: 1000 };
    expect(spacedCode(code.code)).toBe("482 913");
    expect(codeLine(code, 400)).toContain("within 10 minutes");
    expect(codeLine(code, 941)).toContain("within 59 seconds");
    expect(codeLine(code, 1000)).toBeNull();
  });

  it("explains each token verdict and the state of voice notes", async () => {
    expect(verdictLine("accepted", "Vision Bot").text).toBe("Discord accepts the token: the bot is Vision Bot.");
    expect(verdictLine("refused", null).tone).toBe("bad");
    const v = await base();
    expect(voiceNotesLine(v).tone).toBe("ok");
    expect(voiceNotesLine({ ...v, voice_notes: { models: true, decoder: null } }).tone).toBe("warn");
    expect(voiceNotesLine({ ...v, voice_notes: { models: false, decoder: "ffmpeg" } }).text).toContain("speech models");
  });

  it("switches a tool and never adds a Mac-only one", async () => {
    const v = await base();
    expect(toggledTools(v, "open_url")).not.toContain("open_url");
    const off = { ...v, phone_tools: toggledTools(v, "open_url") };
    expect(toggledTools(off, "open_url")).toContain("open_url");
    expect(toggledTools(v, "shell")).toEqual(v.phone_tools);
  });

  it("labels a turn from the phone in the caption", () => {
    const s = reduce(initialState(), { kind: "event", event: { type: "user.utterance", ts: 1, data: { text: "hi", source: "phone" } } });
    expect(s.caption.source).toBe("phone");
    expect(whoSaid("phone")).toBe("You, from the phone");
    expect(whoSaid("text")).toBe("You");
    expect(whoSaid("automation")).toBe("Automation");
  });
});
