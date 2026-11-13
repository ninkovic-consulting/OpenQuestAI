// The Offline mode and Local model blocks of Models. They hold what they know
// of the local models, ask the daemon for it again while a download runs, and
// redraw only what changed, so what is typed or half-confirmed survives.

import type { LocalListing } from "../../net/brain-types";
import type { Json } from "../../net/settings-types";
import { el } from "../dom";
import { localShort } from "../mode";
import type { SettingsContext } from "./context";
import { block, segmented, statusLine } from "./fields";
import { formatBytes } from "./format";
import { catalogRow, customRow, type RowActions } from "./local-catalog";
import { customForm } from "./local-custom";
import { serverForm } from "./local-server";
import { anyRunning, chosenSize, chosenTitle, downloadOf, memoryLine, offersDownload, orderBySize } from "./local-words";
import { offlineBlock } from "./offline-block";

const POLL_MS = 1000;
const IDLE = { state: "idle", done_bytes: 0, total_bytes: null, message: null } as const;

export interface LocalBlocks {
  offline: HTMLElement;
  local: HTMLElement;
}

interface Wanted {
  id: string;
  data: unknown;
  make(): HTMLElement;
}

export function mountLocal(ctx: SettingsContext): LocalBlocks {
  const offlineRoot = block("Offline mode");
  const localRoot = block("Local model");
  let local = ctx.settings.models.local;
  let listing: LocalListing | null = null;
  let loadError: string | null = null;
  let refusal: string | null = null;
  let ready: string | null = null;
  let busy = false;
  let timer: number | undefined;

  // ---------------------------------------------------------------- talking to the daemon

  /** Save a change to the local model or offline mode at once; answers the daemon's refusal, or null. */
  const patch = async (models: Record<string, Json>): Promise<string | null> => {
    const r = await ctx.api.patchSettings({ models });
    if (!r.ok) return r.message;
    local = r.value.settings.models.local;
    void ctx.reload({ redraw: false });
    await refresh();
    return null;
  };

  async function refresh(): Promise<void> {
    const r = await ctx.api.localModels();
    if (!r.ok) {
      loadError = r.message;
      drawAll();
      return;
    }
    const before = listing;
    const now = r.value;
    listing = now;
    loadError = null;
    local = { ...local, backend: now.chosen.backend, model: now.chosen.model, server: now.chosen.server, tools: now.chosen.tools, offline: now.offline };
    if (refusal !== null && before && offersDownload(before) && !offersDownload(now)) {
      refusal = null;
      ready = `${chosenTitle(now)} is on this Mac. You can turn offline mode on now.`;
    }
    drawAll();
    poll();
  }

  function poll(): void {
    window.clearTimeout(timer);
    if (!listing || !anyRunning(listing)) return;
    timer = window.setTimeout(() => {
      if (localRoot.isConnected) void refresh();
    }, POLL_MS);
  }

  const setOffline = async (on: boolean): Promise<void> => {
    busy = true;
    refusal = null;
    ready = null;
    drawOffline();
    const problem = await patch({ offline: on });
    busy = false;
    refusal = problem;
    drawOffline();
  };

  const download = async (repo: string): Promise<void> => {
    const r = await ctx.api.downloadLocal(repo);
    if (r.ok) listing = r.value;
    else notice(r.message, true);
    drawAll();
    poll();
  };

  const titleOf = (repo: string): string => listing?.models.find((m) => m.id === repo)?.title ?? repo;
  const act: RowActions = {
    download,
    async use(repo) {
      const problem = await patch({ ...(local.backend === "mlx" ? {} : { local_backend: "mlx" }), local: repo });
      notice(problem ?? `Now using ${titleOf(repo)} as the local model.`, problem !== null);
    },
    async remove(repo) {
      const r = await ctx.api.deleteLocal(repo);
      if (!r.ok) return r.message;
      listing = r.value;
      drawAll();
      return `Deleted ${titleOf(repo)}, freed ${formatBytes(r.value.freed_bytes)}.`;
    },
  };

  // ---------------------------------------------------------------- the offline block

  function drawOffline(): void {
    const l = listing;
    const offer = refusal !== null && l !== null && offersDownload(l) ? { download: downloadOf(l, l.chosen.model) ?? IDLE, size: chosenSize(l) } : null;
    const parts = offlineBlock(
      { on: local.offline, busy, model: l ? chosenTitle(l) : localShort(local.model), tools: local.tools, refusal, offer, ready },
      { toggle: (on) => void setOffline(on), download: () => void download(local.model) },
    );
    const heading = offlineRoot.firstElementChild;
    offlineRoot.replaceChildren(...(heading ? [heading] : []), ...parts);
  }

  // ---------------------------------------------------------------- the local model block

  const result = el("p", "field-note lm-result");
  result.setAttribute("role", "status");
  function notice(text: string, bad = false): void {
    result.textContent = text;
    result.className = `${bad ? "field-error" : "field-note"} lm-result`;
  }
  const inUseLine = el("div", "lm-inuse");
  const memory = el("p", "field-note lm-memory-line");
  const rows = el("div", "lm-rows");
  const rowNodes = new Map<string, { key: string; node: HTMLElement }>();
  const server = serverForm(ctx.api, { backend: local.backend, server: local.server, model: local.model }, async (address, model) => {
    const problem = await patch({ local_backend: "openai", local_server: address, local: model });
    if (problem === null) notice(`Now using ${model} on ${address} as the local model.`);
    return problem;
  });
  const typed = customForm(async (repo) => {
    const problem = await patch({ local_backend: "mlx", local: repo });
    if (problem !== null) return problem;
    await download(repo);
    return null;
  });
  const insideApp = el("div", "lm-pane");
  insideApp.append(memory, result, rows, typed);
  const onServer = el("div", "lm-pane");
  onServer.append(server);
  const show = (view: string): void => {
    insideApp.hidden = view !== "mlx";
    onServer.hidden = view !== "openai";
  };
  const startView = local.backend === "openai" ? "openai" : "mlx";
  show(startView);
  const choose = segmented(
    "Where the local model runs",
    [
      { value: "mlx", label: "Inside the app" },
      { value: "openai", label: "A local server" },
    ],
    startView,
    show,
  );
  localRoot.append(
    el("p", "field-note", "Answers when offline mode is on or the monthly cap is spent. It runs inside this app, or on a server of its own such as LM Studio or Ollama."),
    choose,
    inUseLine,
    insideApp,
    onServer,
  );
  const loading = statusLine("idle", "Loading the local models…");

  function drawCatalog(): void {
    const l = listing;
    if (!l) {
      rows.replaceChildren(loadError ? statusLine("bad", `The local models could not be listed: ${loadError}`) : loading);
      return;
    }
    memory.textContent = `${memoryLine(l.memory_bytes)} The models run from small to large.`;
    const wanted: Wanted[] = orderBySize(l.models).map((m) => ({ id: m.id, data: m, make: () => catalogRow(m, l, act) }));
    if (l.custom) {
      const custom = l.custom;
      wanted.push({ id: custom.id, data: custom, make: () => customRow(custom, l, act) });
    }
    for (const id of [...rowNodes.keys()]) if (!wanted.some((w) => w.id === id)) rowNodes.delete(id);
    const nodes = wanted.map((w) => {
      const key = JSON.stringify([w.data, l.chosen, l.offline, l.recommended]);
      const kept = rowNodes.get(w.id);
      if (kept?.key === key) return kept.node;
      const node = w.make();
      rowNodes.set(w.id, { key, node });
      return node;
    });
    if (nodes.length !== rows.children.length || nodes.some((n, i) => rows.children[i] !== n)) rows.replaceChildren(...nodes);
  }

  function drawInUse(): void {
    const where =
      local.backend === "openai" ? `${local.model} on the server at ${local.server}` : `${listing ? chosenTitle(listing) : localShort(local.model)}, inside the app`;
    inUseLine.replaceChildren(statusLine("ok", `In use: ${where}.`));
  }

  function drawAll(): void {
    drawOffline();
    drawCatalog();
    drawInUse();
  }

  // Offline mode switched elsewhere (the left panel) shows here too.
  const stop = ctx.store.subscribe((s) => {
    if (!localRoot.isConnected) return stop();
    if (s.mode && s.mode.offline !== local.offline) void refresh();
  });

  drawAll();
  void refresh();
  return { offline: offlineRoot, local: localRoot };
}
