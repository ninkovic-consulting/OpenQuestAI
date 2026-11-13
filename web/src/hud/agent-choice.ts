// An agent as a choice in a list: its name, then the model it thinks with,
// so it is plain which agents are the strong ones.

import type { Agent } from "../net/types";

const CLAUDE = /^claude-([a-z]+)-(\d+)(?:-(\d+))?/;

/** `claude-haiku-5-5` reads "Haiku 5.5"; any other id is shown without its publisher. */
export function modelShort(id: string): string {
  const claude = CLAUDE.exec(id);
  if (claude) {
    const [, family = "", major = "", minor] = claude;
    return `${family.charAt(0).toUpperCase()}${family.slice(1)} ${major}${minor === undefined ? "" : `.${minor}`}`;
  }
  return id.slice(id.lastIndexOf("/") + 1);
}

/** "Tink · Opus 5.5", with the model for careful work when the agent has another one. */
export function agentChoice(agent: Agent): string {
  const model = modelShort(agent.model);
  const heavy = agent.heavy_model ? modelShort(agent.heavy_model) : model;
  return heavy === model ? `${agent.name} · ${model}` : `${agent.name} · ${model} (careful: ${heavy})`;
}
