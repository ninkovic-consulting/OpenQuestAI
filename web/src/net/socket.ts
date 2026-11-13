// The real connection: WebSocket at /ws, `hello` first, reconnect with
// back-off, and reload /api/state, /api/house and /api/jobs after every (re)connect.

import { Api } from "./api";
import { HttpAutomations, type AutomationsApi } from "./automations-api";
import type { Daemon } from "./daemon";
import { HttpImages, type ImagesApi } from "./images-api";
import { HttpJobs, type JobsApi } from "./jobs-api";
import { HttpLibrary, type LibraryApi } from "./library-api";
import { HttpPhone, type PhoneApi } from "./phone-api";
import { HttpProcedures, type ProceduresApi } from "./procedures-api";
import { HttpProposals, type ProposalsApi } from "./proposals-api";
import { asPlan } from "./plan";
import type { Result, SettingsApi } from "./settings-api";
import { HttpSettings } from "./settings-http";
import type { Store } from "./store";
import { asOutbound, envelope, type InboundEvent, type NewRoom, type PostResult, type ProposeResult, type StateSnapshot } from "./types";

const BACKOFF_MIN_MS = 500;
const BACKOFF_MAX_MS = 10_000;
const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_FORBIDDEN_ORIGIN = 4403;

export class SocketDaemon implements Daemon {
  private readonly api: Api;
  readonly settings: SettingsApi;
  readonly automations: AutomationsApi;
  readonly phone: PhoneApi;
  readonly jobs: JobsApi;
  readonly library: LibraryApi;
  readonly images: ImagesApi;
  readonly proposals: ProposalsApi;
  readonly procedures: ProceduresApi;
  private ws: WebSocket | null = null;
  private backoff = BACKOFF_MIN_MS;
  private loadedOnce = false;
  private planLoading = false;
  private planAgain = false;
  private refusedToast = false;

  constructor(
    private readonly store: Store,
    private readonly token: string,
  ) {
    this.api = new Api(token);
    this.settings = new HttpSettings(this.api);
    this.automations = new HttpAutomations(this.api);
    this.phone = new HttpPhone(this.api);
    this.jobs = new HttpJobs(this.api);
    this.library = new HttpLibrary(this.api);
    this.images = new HttpImages(this.api);
    this.proposals = new HttpProposals(this.api);
    this.procedures = new HttpProcedures(this.api);
  }

  start(): void {
    this.connect();
  }

  send(event: InboundEvent): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(event));
    } else {
      this.store.dispatch({ kind: "toast", level: "warn", text: "Not connected to the daemon yet." });
    }
  }

  proposeTools(folder: string): Promise<ProposeResult> {
    return this.api.proposeTools(folder);
  }

  postRoom(room: NewRoom): Promise<PostResult> {
    return this.api.postRoom(room);
  }

  history(): Promise<Result<unknown>> {
    return this.api.call("GET", "/api/history?limit=50");
  }

  private connect(): void {
    this.store.dispatch({ kind: "connection", connection: "connecting" });
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/ws`);
    this.ws = ws;
    ws.addEventListener("open", () => {
      ws.send(JSON.stringify(envelope("hello", { token: this.token })));
      this.backoff = BACKOFF_MIN_MS;
      this.store.dispatch({ kind: "connection", connection: "open" });
      void this.reload();
    });
    ws.addEventListener("message", (msg) => this.onMessage(msg.data));
    ws.addEventListener("close", (ev) => this.onClose(ev.code));
  }

  private onMessage(raw: unknown): void {
    if (typeof raw !== "string") return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    const event = asOutbound(parsed);
    if (event === null) return;
    this.store.dispatch({ kind: "event", event });
    if (event.type === "house.changed") void this.loadPlanIfStale();
  }

  private onClose(code: number): void {
    this.ws = null;
    this.store.dispatch({ kind: "connection", connection: "offline" });
    if ((code === CLOSE_UNAUTHORIZED || code === CLOSE_FORBIDDEN_ORIGIN) && !this.refusedToast) {
      this.refusedToast = true;
      const why = code === CLOSE_UNAUTHORIZED ? "the token was refused" : "this page's origin was refused";
      this.store.dispatch({ kind: "toast", level: "error", text: `The daemon closed the connection: ${why}.` });
    }
    const wait = this.backoff * (0.8 + Math.random() * 0.4);
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
    setTimeout(() => this.connect(), wait);
  }

  private async reload(): Promise<void> {
    try {
      const snapshot = (await this.api.get("/api/state")) as StateSnapshot;
      this.store.dispatch({ kind: "snapshot", snapshot, initial: !this.loadedOnce });
      this.loadedOnce = true;
    } catch (err) {
      this.store.dispatch({ kind: "toast", level: "warn", text: `Could not load the state: ${String(err)}` });
    }
    await this.loadPlan();
    await this.loadJobs();
  }

  /** The board as it stands; events keep it current from here. */
  private async loadJobs(): Promise<void> {
    const r = await this.jobs.list();
    if (r.ok) this.store.dispatch({ kind: "jobs", list: r.value });
    else this.store.dispatch({ kind: "toast", level: "warn", text: `Could not load the jobs: ${r.message}` });
  }

  private async loadPlanIfStale(): Promise<void> {
    const { plan, houseRevision } = this.store.get();
    if (plan === null || houseRevision > plan.revision) await this.loadPlan();
  }

  private async loadPlan(): Promise<void> {
    if (this.planLoading) {
      this.planAgain = true;
      return;
    }
    this.planLoading = true;
    try {
      const plan = asPlan(await this.api.get("/api/house"));
      if (plan === null) {
        this.store.dispatch({ kind: "toast", level: "error", text: "The house plan from the daemon is not in the expected shape." });
      } else {
        this.store.dispatch({ kind: "plan", plan });
      }
    } catch (err) {
      this.store.dispatch({ kind: "toast", level: "warn", text: `Could not load the house: ${String(err)}` });
    } finally {
      this.planLoading = false;
    }
    // A `house.changed` that arrived mid-load may be newer than what was fetched.
    if (this.planAgain) {
      this.planAgain = false;
      await this.loadPlan();
    }
  }
}
