import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/josefin-sans/latin-300.css";
import "@fontsource/josefin-sans/latin-400.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "./styles/tokens.css";
import "./styles/hud.css";
import "./styles/settings.css";

import { mountBuildForm } from "./hud/build-form";
import { mountCaption } from "./hud/caption";
import { el } from "./hud/dom";
import { mountGate } from "./hud/gate";
import { mountInput } from "./hud/input";
import { mountJobs } from "./hud/jobs/view";
import { mountLabels } from "./hud/labels";
import { mountPanel } from "./hud/panel";
import { modelSource } from "./hud/pickers/model-picker";
import { mountRoomCard } from "./hud/room-card";
import { mountSettings, type SettingsView } from "./hud/settings/view";
import { mountWizard } from "./hud/settings/wizard/wizard";
import { mountToasts } from "./hud/toasts";
import type { Daemon } from "./net/daemon";
import { MockDaemon } from "./net/mock";
import { SocketDaemon } from "./net/socket";
import { Store } from "./net/store";
import { readToken } from "./net/token";
import { Stage } from "./scene/stage";

async function connect(store: Store): Promise<Daemon | null> {
  if (new URLSearchParams(location.search).get("mock") === "1") return new MockDaemon(store);
  const token = await readToken();
  if (token === null) {
    store.dispatch({
      kind: "toast",
      level: "error",
      text: "No token: open this page with `vision ui`, or add ?mock=1 to try it without a daemon.",
    });
    store.dispatch({ kind: "connection", connection: "offline" });
    return null;
  }
  return new SocketDaemon(store, token);
}

async function main(): Promise<void> {
  const store = new Store();
  const app = el("div", "app");
  document.body.append(app);
  const panel = mountPanel(app, store);
  const stageRoot = el("main", "stage");
  app.append(stageRoot);
  mountToasts(stageRoot, store);
  const notify = (text: string): void => store.dispatch({ kind: "toast", level: "warn", text });
  const stage = new Stage(stageRoot, store, notify);
  stage.onFrame = mountLabels(stageRoot, store);
  mountCaption(stageRoot, store);
  let settings: SettingsView | null = null;
  const roomCard = mountRoomCard(stageRoot, store, (id) => settings?.open("rooms", id));
  stage.onRoom = (id) => roomCard.show(id);
  stage.start();

  const daemon = await connect(store);
  if (!daemon) return;

  const banner = el("div", "build-banner caps", "Build mode · choose a glowing slot");
  stageRoot.append(banner);
  let building = false;
  const setBuilding = (on: boolean): void => {
    building = on;
    stage.setBuildMode(on);
    banner.classList.toggle("is-on", on);
    panel.buildToggle.classList.toggle("is-on", on);
    panel.buildToggle.textContent = on ? "Done" : "Build";
  };
  const models = modelSource(daemon.settings);
  const propose = (folder: string): ReturnType<typeof daemon.proposeTools> => daemon.proposeTools(folder);
  const form = mountBuildForm(stageRoot, store, daemon, models, () => setBuilding(false));
  panel.buildToggle.addEventListener("click", () => {
    form.close();
    jobs.close();
    setBuilding(!building);
  });
  stage.onSlot = (cell) => form.open(cell);

  const wizard = mountWizard(stageRoot, { api: daemon.settings, store, models, propose });
  const view = mountSettings(stageRoot, { api: daemon.settings, automations: daemon.automations, phone: daemon.phone, store, models, propose, openWizard: () => wizard.open(),
    onShown: (open) => panel.settingsToggle.classList.toggle("is-on", open),
  });
  settings = view;
  const jobs = mountJobs(stageRoot, { api: daemon.jobs, store, onShown: (open) => panel.jobsToggle.classList.toggle("is-on", open) });
  const openSettings = (): void => {
    form.close();
    setBuilding(false);
    wizard.close();
    jobs.close();
    view.open();
  };
  const openJobs = (): void => {
    form.close();
    setBuilding(false);
    wizard.close();
    view.close();
    jobs.open();
  };
  panel.jobsToggle.addEventListener("click", () => (jobs.isOpen() ? jobs.close() : openJobs()));
  panel.settingsToggle.addEventListener("click", () => (view.isOpen() ? view.close() : openSettings()));
  window.addEventListener("keydown", (ev) => {
    if (ev.key === "," && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      if (view.isOpen()) view.close();
      else openSettings();
    }
  });

  mountGate(panel.foot, store, daemon);
  mountInput(stageRoot, store, daemon, [
    () => view.close(),
    () => jobs.back(),
    () => wizard.close(),
    () => form.close(),
    () => {
      if (!building) return false;
      setBuilding(false);
      return true;
    },
    () => stage.home(),
  ], () => daemon.history());
  daemon.start();
  void daemon.settings.settings().then((r) => {
    if (r.ok && r.value.setup.first_run) wizard.open();
  });
}

void main();
