import type { NativeHelpers } from "../../../net/native";
import type { Doctor, DoctorCheck } from "../../../net/settings-types";
import { el } from "../../dom";
import { RESTART_HELP, type Group, type SettingsContext } from "../context";
import { block, button, confirmButton, note, segmented, statusLine, type Tone } from "../fields";

export const macGroup: Group = {
  id: "mac",
  title: "This Mac",
  blurb: "Starting at login, the doctor's checklist of what this Mac has, and restarting the assistant.",
  prefixes: [],
  render(ctx) {
    const root = el("div", "group-body");
    const login = el("div", "login-item");
    const checks = el("div", "doctor");
    checks.append(note("Running the checks…"));
    const doctor = ctx.api.doctor();
    void doctor.then((r) => checks.replaceChildren(...(r.ok ? doctorList(ctx, r.value) : [statusLine("bad", r.message)])));
    loginItem(login, ctx.native, doctor);

    const setup = button("Run setup again");
    setup.addEventListener("click", () => ctx.openWizard());
    const version = note();
    void ctx.native.appInfo?.().then((info) => (version.textContent = info ? `App version ${info.version}.` : ""));

    root.append(
      block("Start at login", login),
      block("Restart", restartControl(ctx), version),
      ...quitBlock(ctx.native),
      block("Setup", el("p", "field-note", "The first-start steps: key, downloads, microphone, name and a project room."), setup),
      block("Doctor", checks),
    );
    return root;
  },
};

function loginItem(root: HTMLElement, native: NativeHelpers, doctor: ReturnType<SettingsContext["api"]["doctor"]>): void {
  const read = native.loginItemEnabled;
  const write = native.setLoginItem;
  if (read && write) {
    const draw = (on: boolean): void => {
      const control = segmented("Start at login", [{ value: "on", label: "On" }, { value: "off", label: "Off" }], on ? "on" : "off", (v) => {
        void write(v === "on").then(read).then(draw);
      });
      root.replaceChildren(control, el("p", "field-note", on ? "The app opens at login, hidden, and starts the assistant." : "The assistant starts when you open the app."));
    };
    void read().then(draw);
    return;
  }
  // Without the app's help: what the doctor found, and how to change it.
  void doctor.then((r) => {
    const check = r.ok ? r.value.checks.find((c) => c.id === "login") : undefined;
    if (!check) {
      root.replaceChildren(el("p", "field-note", "Start at login is set from the app's menu bar item."));
      return;
    }
    const detail = check.detail.charAt(0).toUpperCase() + check.detail.slice(1);
    root.replaceChildren(statusLine(check.status === "ok" ? "ok" : "idle", `${detail}.`));
    if (check.fix) root.append(el("p", "field-note", `To change it: ${check.fix}.`));
  });
}

function restartControl(ctx: SettingsContext): HTMLElement {
  const root = el("div", "restart-control");
  if (!ctx.native.restartDaemon) {
    root.append(el("p", "field-note", RESTART_HELP));
    return root;
  }
  const go = button("Restart the assistant");
  const result = note();
  go.addEventListener("click", () => {
    go.disabled = true;
    void ctx.restart().then((text) => {
      go.disabled = false;
      result.textContent = text;
    });
  });
  root.append(go, result);
  return root;
}

/** Quit is the app's to do, so the block is there only inside the Mac app. */
function quitBlock(native: NativeHelpers): HTMLElement[] {
  const quit = native.quit;
  if (!quit) return [];
  const control = confirmButton(
    "Quit the app",
    { question: "Quit? The assistant stops answering, and its automations and the phone wait until you open the app again.", confirm: "Quit", danger: true },
    async () => {
      await quit();
      return "Quitting…";
    },
  );
  return [block("Quit", control)];
}

function tone(c: DoctorCheck): Tone {
  if (c.status === "ok") return "ok";
  return c.needed ? "bad" : "idle";
}

function doctorList(ctx: SettingsContext, d: Doctor): HTMLElement[] {
  const head = statusLine(d.ok ? "ok" : "bad", d.ok ? "Everything needed is in place." : "Something needed is missing.");
  const list = el("ul", "check-list");
  for (const c of d.checks) {
    const item = el("li", `check is-${c.status}`);
    const line = el("div", "check-line");
    line.append(statusLine(tone(c), c.title), el("span", "check-detail", c.detail), el("span", "tag", c.needed ? "needed" : "optional"));
    item.append(line);
    if (c.status !== "ok") {
      item.append(el("p", "field-note", `For ${c.needed_for}. ${c.fix ? `Fix: ${c.fix}.` : ""}`));
      if (d.fixable.includes(c.id)) {
        const fix = button("Fix");
        const result = note();
        fix.addEventListener("click", () => {
          fix.disabled = true;
          void ctx.api.fix(c.id).then((r) => {
            result.textContent = r.ok ? r.value.message : r.message;
            fix.disabled = r.ok && r.value.started;
          });
        });
        const actions = el("div", "row-actions");
        actions.append(fix, result);
        item.append(actions);
      }
    }
    list.append(item);
  }
  return [head, list];
}
