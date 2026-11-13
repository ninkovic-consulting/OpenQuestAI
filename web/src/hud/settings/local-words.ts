// The local-model catalog in words and decisions, apart from the DOM: what a
// fit means, the order of the list, which model is in use, what may be deleted.

import type { Fit, LocalDownload, LocalListing, LocalModelRow } from "../../net/brain-types";
import { formatBytes, formatTokens } from "./format";
import type { Tone } from "./fields";

const GIB = 1024 ** 3;

const FIT: Record<Fit, { tone: Tone; words: string; help: string }> = {
  comfortable: { tone: "ok", words: "Runs comfortably", help: "This Mac has memory to spare for it." },
  tight: { tone: "warn", words: "Tight fit", help: "It runs, but other apps may slow down while it does." },
  too_big: { tone: "bad", words: "Too big for this Mac", help: "It will not run well here, or not at all." },
};

export const fitTone = (fit: Fit): Tone => FIT[fit].tone;
export const fitWords = (fit: Fit): string => FIT[fit].words;
export const fitHelp = (fit: Fit): string => FIT[fit].help;

/** The catalog from small to large by what it takes on disk; the daemon's own order is by file, not by size. */
export function orderBySize(models: readonly LocalModelRow[]): LocalModelRow[] {
  return [...models].sort((a, b) => a.size_bytes - b.size_bytes);
}

/** This Mac's memory in one line: "This Mac has 16 GB of memory." */
export function memoryLine(bytes: number): string {
  return `This Mac has ${Math.round(bytes / GIB)} GB of memory.`;
}

/** What the model can do with tools, in a few words. */
export function toolsWords(row: Pick<LocalModelRow, "tools" | "tools_recommended">): string {
  if (!row.tools) return "Talks only, no tools";
  return row.tools_recommended ? "Uses tools well" : "Can use tools, not always reliably";
}

/** The small print: "262k tokens of context · apache-2.0". */
export const finePrint = (row: LocalModelRow): string => `${formatTokens(row.context)} tokens of context · ${row.license}`;

/** Whether the model on this Mac is the one the local brain runs. */
export function inUse(listing: LocalListing, repo: string): boolean {
  return listing.chosen.backend === "mlx" && listing.chosen.model === repo;
}

/** The download of a repo the listing knows, catalog or custom; undefined for any other. */
export function downloadOf(listing: LocalListing, repo: string): LocalDownload | undefined {
  return listing.models.find((m) => m.id === repo)?.download ?? (listing.custom?.id === repo ? listing.custom.download : undefined);
}

/** Whether any model is downloading now, so the listing should be asked for again. */
export function anyRunning(listing: LocalListing): boolean {
  return [...listing.models.map((m) => m.download), ...(listing.custom ? [listing.custom.download] : [])].some((d) => d.state === "running");
}

/** Why a model may not be deleted now, or null when it may. */
export function deleteBlock(listing: LocalListing, repo: string): string | null {
  if (listing.offline && inUse(listing, repo)) return "Offline mode is using it. Choose another model or turn offline mode off first.";
  if (downloadOf(listing, repo)?.state === "running") return "It is still downloading.";
  return null;
}

/** The question before a delete. */
export function deleteQuestion(title: string, bytes: number | null): string {
  const freed = bytes === null ? "" : ` This frees ${formatBytes(bytes)}.`;
  return `Delete ${title} from this Mac?${freed} It can be downloaded again.`;
}

/**
 * Whether a refusal to turn offline mode on is for want of the model, so that
 * the window offers its download: the model runs inside the app and is not here.
 */
export function offersDownload(listing: LocalListing | null): boolean {
  if (!listing || listing.chosen.backend !== "mlx") return false;
  const d = downloadOf(listing, listing.chosen.model);
  return d === undefined || d.state !== "done";
}

/** The size the download of the chosen model will take, when the listing knows it. */
export function chosenSize(listing: LocalListing): number | null {
  const row = listing.models.find((m) => m.id === listing.chosen.model);
  return row?.size_bytes ?? listing.custom?.download.total_bytes ?? null;
}

/** The chosen model's name for people: the catalog's title, else the id. */
export function chosenTitle(listing: LocalListing): string {
  return listing.models.find((m) => m.id === listing.chosen.model)?.title ?? listing.chosen.model;
}
