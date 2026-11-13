// The wizard's first steps: welcome, the API key, the downloads and the microphone.

import type { KeyAnswer } from "../../../net/settings-types";
import { el } from "../../dom";
import { downloadControl } from "../download-control";
import { block } from "../fields";
import { formatDownload, keySourceWords, verdictWords } from "../format";
import { keyForm, keyStatus } from "../key-parts";
import { micPermission, voiceTest } from "../voice-parts";
import type { StepView, WizardEnv } from "./step";

export function welcomeStep(env: WizardEnv): StepView {
  const name = env.settings.assistant.name;
  const list = el("ol", "wizard-list");
  for (const line of [
    "Your Anthropic API key, so it can talk to Claude.",
    "Optional downloads: a local model for offline answers, and speech for talking out loud.",
    "The microphone, with a three-second test.",
    "Its name.",
    "What it should call you, and what business you run.",
    "Project folders for one of the rooms, if you like.",
  ]) {
    list.append(el("li", "", line));
  }
  return {
    heading: `Welcome to ${name}`,
    lead: "A few steps get the assistant ready. Every step can be skipped and done later in Settings.",
    body: list,
    next: "Begin",
    finish: () => Promise.resolve({ status: "done", text: "" }),
  };
}

export function keyStep(env: WizardEnv): StepView {
  const key = env.settings.key;
  let answer: KeyAnswer | null = null;
  const status = block("Now", keyStatus(key));
  const body = el("div");
  body.append(
    status,
    keyForm(env.api, key.stored, (a) => {
      answer = a;
      status.querySelector(".status")?.replaceWith(keyStatus({ stored: a.stored, source: a.source }));
    }),
  );
  return {
    heading: "Your API key",
    lead: key.stored ? "A key is already stored. Verify it, or paste a new one to replace it." : "Paste the key from console.anthropic.com, Settings, API keys. It is stored in the Keychain and never shown again.",
    body,
    finish: () => {
      if (answer) return Promise.resolve({ status: "done", text: `${keySourceWords(answer.source)}. ${verdictWords(answer.verdict)}` });
      if (key.stored) return Promise.resolve({ status: "done", text: keySourceWords(key.source) });
      return Promise.resolve({ status: "skipped", text: "No key yet; add it in Settings, API key." });
    },
  };
}

export function downloadsStep(env: WizardEnv): StepView {
  const body = el("div", "wizard-downloads");
  body.append(
    block("Local model", el("p", "field-note", "Answers when you are offline or over the monthly cap. Runs on this Mac."), downloadControl(env.api, "local_model")),
    block("Speech models", el("p", "field-note", "Hear you and speak back. Needed for talking out loud."), downloadControl(env.api, "speech_models")),
  );
  return {
    heading: "Downloads",
    lead: "Both are optional and download in the background; you can carry on while they run.",
    body,
    finish: async () => {
      const r = await env.api.downloads();
      if (!r.ok) return { status: "skipped", text: r.message };
      const local = r.value.local_model;
      const speech = r.value.speech_models;
      const started = [local, speech].some((d) => d.state === "running" || d.state === "done");
      return { status: started ? "done" : "skipped", text: `Local model: ${lowerFirst(formatDownload(local))}. Speech models: ${lowerFirst(formatDownload(speech))}.` };
    },
  };
}

const lowerFirst = (text: string): string => text.charAt(0).toLowerCase() + text.slice(1);

export function microphoneStep(env: WizardEnv): StepView {
  let tested = false;
  const body = el("div");
  body.append(
    block("Permission", micPermission(env.native, env.settings.voice)),
    block(
      "Test",
      el("p", "field-note", "Records three seconds, writes down what it heard and says a sentence back. This opens the microphone."),
      voiceTest(env.api, (ok) => (tested = tested || ok)),
    ),
  );
  return {
    heading: "The microphone",
    lead: "To talk out loud, the assistant needs the microphone. Nothing listens until you turn voice on or run the test.",
    body,
    finish: () => Promise.resolve(tested ? { status: "done", text: "The microphone works; the test heard you." } : { status: "skipped", text: "Not tested; try it in Settings, Voice." }),
  };
}
