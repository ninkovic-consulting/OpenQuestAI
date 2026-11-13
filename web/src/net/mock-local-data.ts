// Mock mode's local-model catalog: the daemon's own (house/local_models.toml),
// and a Mac to measure it against.

import type { Fit, LocalModelRow } from "./brain-types";

export const GIB = 1024 ** 3;
/** The pretend Mac: 24 GB, which gives every fit at once. */
export const MOCK_MEMORY = 24 * GIB;
export const DEFAULT_REPO = "mlx-community/Qwen3-4B-Instruct-2507-4bit";
/** The pretend local server (LM Studio's usual address) and the models it holds. */
export const MOCK_SERVER = "http://127.0.0.1:1234/v1";
export const MOCK_SERVER_MODELS = ["qwen3-8b", "llama-3.2-3b-instruct", "gemma-3-12b-it"];
/** What a model typed by hand weighs. */
export const CUSTOM_BYTES = 3_400_000_000;

type Entry = Omit<LocalModelRow, "fit" | "on_disk_bytes" | "download">;

const entry = (id: string, title: string, good_at: string, kind: string, params_b: number, size_bytes: number, memory_gb: number, context: number, tools: boolean, tools_recommended: boolean, license = "apache-2.0"): Entry => ({
  id, title, good_at, kind, params_b, size_bytes, memory_gb, context, tools, tools_recommended, license,
});

export const CATALOG: readonly Entry[] = [
  entry(DEFAULT_REPO, "Qwen3 4B Instruct", "quick everyday answers; the default", "general", 4.0, 2_278_969_697, 8, 262_144, true, false),
  entry("mlx-community/Qwen3.5-4B-MLX-4bit", "Qwen3.5 4B", "a newer small model; thinks before it answers", "general", 4.7, 3_061_129_077, 8, 262_144, true, false),
  entry("mlx-community/Qwen3-8B-4bit", "Qwen3 8B", "steadier answers than the 4B models", "general", 8.2, 4_623_782_544, 16, 40_960, true, false),
  entry("mlx-community/Qwen3.5-9B-MLX-4bit", "Qwen3.5 9B", "the smallest model that uses tools well", "general", 9.7, 5_977_071_067, 16, 262_144, true, true),
  entry("mlx-community/gpt-oss-20b-MXFP4-Q8", "gpt-oss 20B", "reasoning and explanations; talk only here", "general", 20.9, 12_104_215_835, 24, 131_072, false, false),
  entry("mlx-community/Qwen3.8-27B-4bit", "Qwen3.8 27B", "the smartest model for 32 GB; slower than a mixture of experts", "general", 27.8, 16_074_308_726, 32, 262_144, true, true),
  entry("mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit", "Qwen3 Coder 30B", "code, fast (3B active of 30B)", "code", 30.5, 17_197_087_456, 32, 262_144, true, true),
  entry("mlx-community/gemma-4-31b-it-4bit", "Gemma 4 31B", "careful writing and many languages", "general", 31.3, 18_444_419_448, 32, 262_144, true, true),
  entry("mlx-community/Qwen3.6-35B-A3B-4bit", "Qwen3.6 35B A3B", "smart and fast (3B active of 36B); good with tools", "general", 36.0, 20_429_166_969, 36, 262_144, true, true),
  entry("mlx-community/Llama-3.3-70B-Instruct-4bit", "Llama 3.3 70B", "broad knowledge; talk only here", "general", 70.6, 39_705_992_854, 96, 131_072, false, false, "llama3.3"),
  entry("mlx-community/gpt-oss-120b-MXFP4-Q8", "gpt-oss 120B", "strong reasoning; talk only here", "general", 116.8, 63_414_988_811, 128, 131_072, false, false),
  entry("mlx-community/Qwen3.5-122B-A10B-4bit", "Qwen3.5 122B A10B", "the strongest here, with tools (10B active of 125B)", "general", 125.1, 69_620_617_473, 128, 262_144, true, true),
];

const GPU_SHARE = 0.75;
const TIGHT_EXTRA = 1_000_000_000;

/** How a model fits a Mac with this much memory (vision/brains/catalog.py). */
export function fitOf(m: Pick<Entry, "memory_gb" | "size_bytes">, memory: number): Fit {
  if (memory >= m.memory_gb * GIB) return "comfortable";
  return m.size_bytes + TIGHT_EXTRA <= memory * GPU_SHARE ? "tight" : "too_big";
}

/** The best general model that fits comfortably, one that can use tools first. */
export function recommendedOf(memory: number): string | null {
  const fits = CATALOG.filter((m) => m.kind === "general" && fitOf(m, memory) === "comfortable");
  const chosen = fits.filter((m) => m.tools);
  return (chosen.length > 0 ? chosen : fits).at(-1)?.id ?? null;
}
