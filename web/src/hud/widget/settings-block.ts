// Settings, This Mac, "Widget and shortcuts": the widget on or off, the two
// global shortcuts, what the app shows when it opens, and what closing the
// house window does. These are the Mac
// app's own preferences, read and written through its bridge, so a plain
// browser shows nothing of this block.

import type { NativeHelpers } from "../../net/native";
import { type ShortcutStatus, SHORTCUT_OFF, shortcutLine, type WidgetPrefs, type WidgetPrefsChange } from "../../net/shell-prefs";
import { el } from "../dom";
import { block, fieldRow, segmented, statusLine } from "../settings/fields";

export function widgetBlock(native: NativeHelpers): HTMLElement[] {
  const read = native.widgetPrefs;
  const write = native.setWidgetPrefs;
  if (!read || !write) return [];
  const body = el("div", "widget-prefs");
  body.append(el("p", "field-note", "Reading the app's preferences…"));

  const change = (c: WidgetPrefsChange): void => {
    void write(c).then((p) => (p ? draw(p) : body.replaceChildren(statusLine("bad", "The app did not take the change."))));
  };

  const shortcut = (label: string, key: "summon" | "talk", p: WidgetPrefs, s: ShortcutStatus, help: string): HTMLElement => {
    const select = el("select");
    select.append(new Option("Off", SHORTCUT_OFF), ...p.shortcuts.map((o) => new Option(o.label, o.id)));
    select.value = p[key];
    select.addEventListener("change", () => change(key === "summon" ? { summon: select.value } : { talk: select.value }));
    const line = shortcutLine(p[key], s);
    const row = fieldRow(label, select, { note: help });
    row.append(statusLine(line.tone, line.text));
    return row;
  };

  const draw = (p: WidgetPrefs): void => {
    const widget = segmented("Widget", [{ value: "on", label: "On" }, { value: "off", label: "Off" }], p.widget ? "on" : "off", (v) =>
      change({ widget: v === "on" }),
    );
    const opens = segmented(
      "When the app opens",
      [
        { value: "house", label: "The house" },
        { value: "widget", label: "Only the widget" },
        { value: "menubar", label: "Only the menu bar" },
      ],
      p.openWith,
      (v) => change({ openWith: v === "widget" || v === "menubar" ? v : "house" }),
    );
    body.replaceChildren(
      fieldRow("Widget", widget, {
        note: p.widget
          ? "A small window that floats above every app, on every desktop. Hiding it never stops the assistant."
          : "It stays hidden until a shortcut or the menu bar item calls it up.",
      }),
      shortcut("Summon", "summon", p, p.status.summon, "Brings up the widget with the cursor in its field, from any app; again, sends it away."),
      shortcut("Push to talk", "talk", p, p.status.talk, "Hold to talk, from any app; let go to stop."),
      fieldRow("When the app opens", opens, {
        note: "At login the app always opens hidden; the widget shows when it is on.",
      }),
      fieldRow("When I close the house window", statusLine("idle", "It stays running in the menu bar, without a Dock icon, until you open the house again."), {
        note: "Minimize in the left panel does the same.",
      }),
    );
  };

  void read().then((p) => (p ? draw(p) : body.replaceChildren(statusLine("bad", "The app's preferences could not be read."))));
  return [block("Widget and shortcuts", body)];
}
