// Words and numbers for the settings screen, apart from the DOM.

import type { Download, KeySource, ModelInfo, ModelPrice, Verdict } from "../../net/settings-types";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Dollars per million tokens: "$3", "$0.80", "$1.25". */
export function formatRate(usd: number): string {
  return Number.isInteger(usd) ? `$${usd}` : `$${usd.toFixed(2)}`;
}

/** "$3 in / $15 out per million tokens", or "price not known". */
export function formatPrice(price: ModelPrice | null): string {
  if (!price) return "price not known";
  return `${formatRate(price.input_per_mtok)} in / ${formatRate(price.output_per_mtok)} out per million tokens`;
}

/** "30 Nov 2026" from "2026-11-30"; the text as it came when it is not a date. */
export function formatDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  if (!m || !month) return iso;
  return `${Number(m[3])} ${month.slice(0, 3)} ${m[1]}`;
}

/** One line for a dropdown option: name, price per million tokens in / out, and the retiring date. */
export function modelOption(model: ModelInfo): string {
  const price = model.price ? `${formatRate(model.price.input_per_mtok)} / ${formatRate(model.price.output_per_mtok)} per M` : "price not known";
  const retires = model.retires_at ? ` · retires ${formatDay(model.retires_at)}` : "";
  return `${model.display_name} · ${price}${retires}`;
}

/** A token count: "1M", "200k". */
export function formatTokens(n: number): string {
  if (n >= 1e6) return `${Number((n / 1e6).toFixed(1))}M`;
  return `${Math.round(n / 1000)}k`;
}

/** Bytes as people read them: "2.1 GB", "640 MB". */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} B`;
}

/** A download's state in a few words. */
export function formatDownload(d: Download): string {
  const total = d.total_bytes === null ? null : formatBytes(d.total_bytes);
  switch (d.state) {
    case "done":
      return total ? `Downloaded, ${total}` : "Downloaded";
    case "running":
      return total ? `Downloading… ${formatBytes(d.done_bytes)} of ${total}` : `Downloading… ${formatBytes(d.done_bytes)}`;
    case "failed":
      return d.message ? `Did not finish: ${d.message}` : "Did not finish";
    case "idle":
      return total ? `Not downloaded · about ${total}` : "Not downloaded";
  }
}

/** The share of a download that is done, 0 to 1; null when the size is not known. */
export function downloadShare(d: Download): number | null {
  if (d.state === "done") return 1;
  if (!d.total_bytes) return null;
  return Math.min(1, d.done_bytes / d.total_bytes);
}

/** "November 2026" from "2026-11". */
export function formatMonth(month: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  const name = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && name ? `${name} ${m[1]}` : month;
}

/** "12 Nov 2026, 13:05" from seconds since 1970, in local time. */
export function formatWhen(seconds: number): string {
  const d = new Date(seconds * 1000);
  const month = MONTHS[d.getMonth()] ?? "";
  return `${d.getDate()} ${month.slice(0, 3)} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function keySourceWords(source: KeySource | null): string {
  switch (source) {
    case "keychain":
      return "Stored in the Keychain";
    case "env_file":
      return "Read from the .env file";
    case "environment":
      return "Read from an environment variable";
    case null:
      return "No key stored";
  }
}

export function verdictWords(verdict: Verdict): string {
  switch (verdict) {
    case "accepted":
      return "Anthropic accepted the key.";
    case "refused":
      return "Anthropic refused the key. Copy it again from console.anthropic.com, Settings, API keys.";
    case "unreachable":
      return "Anthropic could not be reached, so the key was not checked. Try again when online.";
    case "none":
      return "There is no key to check yet.";
  }
}

const VOICE_KIND: Record<string, string> = { af: "American, female", am: "American, male", bf: "British, female", bm: "British, male" };

/** "Heart (American, female)" from "af_heart". */
export function voiceLabel(id: string): string {
  const [kind, name] = id.split("_");
  const where = kind ? VOICE_KIND[kind] : undefined;
  if (!where || !name) return id;
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} (${where})`;
}

/** What a backup's level means, for the list. */
export function backupWords(level: string): string {
  switch (level) {
    case "settings":
      return "Before resetting settings";
    case "house":
      return "Before resetting the house";
    case "everything":
      return "Before starting over";
    case "restore":
      return "Before restoring a backup";
    default:
      return level;
  }
}
