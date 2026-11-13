import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/josefin-sans/latin-300.css";
import "@fontsource/josefin-sans/latin-400.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "./styles/tokens.css";
import "./styles/hud.css";
import "./styles/rooms.css";
import "./styles/settings.css";
import "./styles/local.css";
import "./styles/library.css";

import { mountBuildForm } from "./hud/build-form";
import { mountCaption } from "./hud/caption";
import { el } from "./hud/dom";
import { mountGate } from "./hud/gate";
import { mountInput } from "./hud/input";
import { mountJobs } from "./hud/jobs/view";
import { mountLabels } from "./hud/labels";
import { mountOfflineSwitch } from "./hud/offline-switch";
import { mountPanel } from "./hud/panel";
import { mountProposals } from "./hud/proposals/view";
import { modelSource } from "./hud/pickers/model-picker";
import { mountRoomCard } from "./hud/rooms/card";
import { RoomSelection } from "./hud/rooms/selection";
import { mountSettings } from "./hud/settings/view";
import { mountWizard } from "./hud/settings/wizard/wizard";
import { mountToasts } from "./hud/toasts";
import { connect } from "./net/connect";
import { Store } from "./net/store";
import { Stage } from "./scene/stage";

async function main(): Promise<void> {
  const store = new Store();
  const app = el("div", "app");
  document.body.append(app);
  const selection = new RoomSelection();
  let focusRoom: (id: string) => void = () => {};
  const panel = mountPanel(app, store, { selection, focus: (id) => focusRoom(id) });
  const stageRoot = el("main", "stage");
  app.append(stageRoot);
  mountToasts(stageRoot, store);
  const notify = (text: string): void => store.dispatch({ kind: "toast", level: "warn", text });
  const stage = new Stage(stageRoot, store, notify);
  stage.onFrame = mountLabels(stageRoot, store, selection);
  mountCaption(stageRoot, store);
  stage.onRoom = (id) => selection.set(id);
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
    proposals.close();
    setBuilding(!building);
  });
  stage.onSlot = (cell) => form.open(cell);

  const wizard = mountWizard(stageRoot, { api: daemon.settings, store, models, propose });
  const view = mountSettings(stageRoot, { api: daemon.settings, automations: daemon.automations, phone: daemon.phone, library: daemon.library, store, models, propose, openWizard: () => wizard.open(),
    onShown: (open) => panel.settingsToggle.classList.toggle("is-on", open),
  });
  const jobs = mountJobs(stageRoot, { api: daemon.jobs, store, onShown: (open) => panel.jobsToggle.classList.toggle("is-on", open) });
  const proposals = mountProposals(stageRoot, {
    api: daemon.proposals,
    procedures: daemon.procedures,
    store,
    onShown: (open) => panel.proposalsToggle.classList.toggle("is-on", open),
  });
  const openSettings = (): void => {
    form.close();
    setBuilding(false);
    wizard.close();
    jobs.close();
    proposals.close();
    view.open();
  };
  const openJobs = (jobId?: string): void => {
    form.close();
    setBuilding(false);
    wizard.close();
    view.close();
    proposals.close();
    jobs.open(jobId);
  };
  const openProposals = (): void => {
    form.close();
    setBuilding(false);
    wizard.close();
    view.close();
    jobs.close();
    proposals.open();
  };
  focusRoom = (id) => {
    setBuilding(false);
    stage.focusRoom(id);
  };
  const card = mountRoomCard(stageRoot, {
    store,
    jobs: daemon.jobs,
    selection,
    onEdit: (id) => {
      jobs.close();
      proposals.close();
      view.open("rooms", id);
    },
    onOpenJob: openJobs,
  });
  stage.coverLeft = card.cover;
  panel.jobsToggle.addEventListener("click", () => (jobs.isOpen() ? jobs.close() : openJobs()));
  panel.proposalsToggle.addEventListener("click", () => (proposals.isOpen() ? proposals.close() : openProposals()));
  panel.settingsToggle.addEventListener("click", () => (view.isOpen() ? view.close() : openSettings()));
  window.addEventListener("keydown", (ev) => {
    if (ev.key === "," && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      if (view.isOpen()) view.close();
      else openSettings();
    }
  });

  mountOfflineSwitch(panel.modeSlot, store, daemon.settings);
  mountGate(panel.foot, store, daemon);
  mountInput(stageRoot, store, daemon, [
    () => view.close(),
    () => jobs.back(),
    () => proposals.back(),
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
