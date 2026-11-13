// The Mac app's script bridge (`window.pywebview.api`), typed once. Every
// helper is optional: an older app, or a plain browser, has fewer or none, so
// each one is feature-detected and the screen hides what cannot work.

import { asWidgetPrefs, type WidgetPrefs, type WidgetPrefsChange } from "./shell-prefs";

export type MicStatus = "granted" | "denied" | "restricted" | "undetermined";
export type SettingsPane = "microphone" | "login-items";

interface PywebviewApi {
  token?: () => Promise<string>;
  chooseFolder?: () => Promise<string | null>;
  micStatus?: () => Promise<string>;
  requestMic?: () => Promise<string>;
  openSystemSettings?: (pane: SettingsPane) => Promise<unknown>;
  loginItemEnabled?: () => Promise<boolean>;
  setLoginItem?: (enabled: boolean) => Promise<unknown>;
  restartDaemon?: () => Promise<unknown>;
  appInfo?: () => Promise<unknown>;
  quit?: () => Promise<unknown>;
  finishDeleteAll?: (summary: string) => Promise<unknown>;
  widgetPrefs?: () => Promise<unknown>;
  setWidgetPrefs?: (changes: WidgetPrefsChange) => Promise<unknown>;
  showWidget?: (shown: boolean) => Promise<unknown>;
  dismissWidget?: () => Promise<unknown>;
  openHouse?: () => Promise<unknown>;
  fitWidget?: (height: number, handle: number[]) => Promise<unknown>;
  goToBackground?: () => Promise<unknown>;
  safeAreaTop?: () => Promise<unknown>;
}

interface PywebviewBridge {
  api: PywebviewApi;
}

declare global {
  interface Window {
    pywebview?: PywebviewBridge;
  }
}

/** The bridge, waiting up to `waitMs` for pywebview to announce it; null in a plain browser. */
export function bridge(waitMs: number): Promise<PywebviewApi | null> {
  if (window.pywebview) return Promise.resolve(window.pywebview.api);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), waitMs);
    window.addEventListener(
      "pywebviewready",
      () => {
        clearTimeout(timer);
        resolve(window.pywebview?.api ?? null);
      },
      { once: true },
    );
  });
}

/** What the app says about itself; only the version is shown. */
export interface AppInfo {
  version: string;
}

/** The helpers this window has; a missing one is null. */
export interface NativeHelpers {
  chooseFolder: (() => Promise<string | null>) | null;
  micStatus: (() => Promise<MicStatus>) | null;
  requestMic: (() => Promise<MicStatus>) | null;
  openSystemSettings: ((pane: SettingsPane) => Promise<void>) | null;
  loginItemEnabled: (() => Promise<boolean>) | null;
  setLoginItem: ((enabled: boolean) => Promise<void>) | null;
  restartDaemon: (() => Promise<void>) | null;
  appInfo: (() => Promise<AppInfo | null>) | null;
  /** Quit the app, which also stops the assistant it started. */
  quit: (() => Promise<void>) | null;
  /**
   * After Delete all data: turn off Start at login, forget the window's stored data and the
   * app's own preferences, show `summary`, and quit without starting the assistant again.
   */
  finishDeleteAll: ((summary: string) => Promise<void>) | null;
  /** The widget and the global shortcuts: the shell's own preferences (shell-prefs.ts). */
  widgetPrefs: (() => Promise<WidgetPrefs | null>) | null;
  setWidgetPrefs: ((changes: WidgetPrefsChange) => Promise<WidgetPrefs | null>) | null;
  showWidget: ((shown: boolean) => Promise<void>) | null;
  /** The keyboard goes back to the app in front; the widget stays if it is on. */
  dismissWidget: (() => Promise<void>) | null;
  openHouse: (() => Promise<void>) | null;
  /** The widget page's height, and its drag handle as [x, y, width, height] from its top left. */
  fitWidget: ((height: number, handle: number[]) => Promise<void>) | null;
  /** Minimize: close the house window and keep running in the menu bar only (no Dock icon); nothing stops. */
  goToBackground: (() => Promise<void>) | null;
  /** The top strip of the screen the window is on that a camera notch hides, in points; 0 without one. */
  safeAreaTop: (() => Promise<number>) | null;
}

const MIC: ReadonlySet<string> = new Set<MicStatus>(["granted", "denied", "restricted", "undetermined"]);

export function asMicStatus(v: unknown): MicStatus {
  return typeof v === "string" && MIC.has(v) ? (v as MicStatus) : "undetermined";
}

export function asAppInfo(v: unknown): AppInfo | null {
  if (typeof v !== "object" || v === null) return null;
  const version = (v as Record<string, unknown>)["version"];
  return typeof version === "string" ? { version } : null;
}

/** The helpers of the bridge as it is now; read it again when a screen opens. */
export function nativeHelpers(): NativeHelpers {
  const api = window.pywebview?.api;
  if (!api) return withNone();
  const { chooseFolder, micStatus, requestMic, openSystemSettings, loginItemEnabled, setLoginItem, restartDaemon, appInfo, quit, finishDeleteAll } = api;
  const { widgetPrefs, setWidgetPrefs, showWidget, dismissWidget, openHouse, fitWidget, goToBackground, safeAreaTop } = api;
  return {
    chooseFolder: chooseFolder
      ? async () => {
          const path = await chooseFolder.call(api);
          return typeof path === "string" && path !== "" ? path : null;
        }
      : null,
    micStatus: micStatus ? async () => asMicStatus(await micStatus.call(api)) : null,
    requestMic: requestMic ? async () => asMicStatus(await requestMic.call(api)) : null,
    openSystemSettings: openSystemSettings ? async (pane) => void (await openSystemSettings.call(api, pane)) : null,
    loginItemEnabled: loginItemEnabled ? async () => (await loginItemEnabled.call(api)) === true : null,
    setLoginItem: setLoginItem ? async (enabled) => void (await setLoginItem.call(api, enabled)) : null,
    restartDaemon: restartDaemon ? async () => void (await restartDaemon.call(api)) : null,
    appInfo: appInfo ? async () => asAppInfo(await appInfo.call(api)) : null,
    quit: quit ? async () => void (await quit.call(api)) : null,
    finishDeleteAll: finishDeleteAll ? async (summary) => void (await finishDeleteAll.call(api, summary)) : null,
    widgetPrefs: widgetPrefs ? async () => asWidgetPrefs(await widgetPrefs.call(api)) : null,
    setWidgetPrefs: setWidgetPrefs ? async (changes) => asWidgetPrefs(await setWidgetPrefs.call(api, changes)) : null,
    showWidget: showWidget ? async (shown) => void (await showWidget.call(api, shown)) : null,
    dismissWidget: dismissWidget ? async () => void (await dismissWidget.call(api)) : null,
    openHouse: openHouse ? async () => void (await openHouse.call(api)) : null,
    fitWidget: fitWidget ? async (height, handle) => void (await fitWidget.call(api, height, handle)) : null,
    goToBackground: goToBackground ? async () => void (await goToBackground.call(api)) : null,
    safeAreaTop: safeAreaTop ? async () => asInset(await safeAreaTop.call(api)) : null,
  };
}

/** A safe-area inset in points: a finite number from 0 up, else 0. */
export function asInset(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
}

function withNone(): NativeHelpers {
  return {
    chooseFolder: null,
    micStatus: null,
    requestMic: null,
    openSystemSettings: null,
    loginItemEnabled: null,
    setLoginItem: null,
    restartDaemon: null,
    appInfo: null,
    quit: null,
    finishDeleteAll: null,
    widgetPrefs: null,
    setWidgetPrefs: null,
    showWidget: null,
    dismissWidget: null,
    openHouse: null,
    fitWidget: null,
    goToBackground: null,
    safeAreaTop: null,
  };
}
