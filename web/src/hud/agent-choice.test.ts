import { describe, expect, it } from "vitest";

import { agentChoice, modelShort } from "./agent-choice";

describe("agent choices", () => {
  it("name Claude models by family and version", () => {
    expect(modelShort("claude-haiku-5-5")).toBe("Haiku 5.5");
    expect(modelShort("claude-opus-5-5")).toBe("Opus 5.5");
    expect(modelShort("claude-sonnet-5")).toBe("Sonnet 5");
    expect(modelShort("claude-haiku-5-5-20261001")).toBe("Haiku 5.5");
  });

  it("show any other model without its publisher", () => {
    expect(modelShort("mlx-community/Qwen3-4B-Instruct-2507-4bit")).toBe("Qwen3-4B-Instruct-2507-4bit");
    expect(modelShort("my-model")).toBe("my-model");
  });

  it("put the model beside the agent's name, and the careful one when it differs", () => {
    expect(agentChoice({ id: "maker", name: "Tink", model: "claude-opus-5-5" })).toBe("Tink · Opus 5.5");
    expect(agentChoice({ id: "checker", name: "Tock", model: "claude-haiku-5-5", heavy_model: "claude-opus-5-5" })).toBe(
      "Tock · Haiku 5.5 (careful: Opus 5.5)",
    );
    expect(agentChoice({ id: "steward", name: "Brass", model: "claude-haiku-5-5", heavy_model: "claude-haiku-5-5" })).toBe("Brass · Haiku 5.5");
  });
});
