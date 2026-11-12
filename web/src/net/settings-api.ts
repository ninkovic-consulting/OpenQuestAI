// What the settings screen, the wizard and the pickers ask of the daemon.
// The real HTTP client (settings-http.ts) and mock mode (mock-settings.ts)
// both implement it.

import type {
  Backup,
  Doctor,
  Downloads,
  DownloadWhat,
  FieldError,
  FixAnswer,
  FolderSuggestion,
  KeyAnswer,
  ModelListing,
  PatchAnswer,
  ResetAnswer,
  ResetLevel,
  RestoreAnswer,
  RoomPatch,
  Settings,
  SettingsPatch,
  Verdict,
  VoiceDevices,
  VoiceState,
  VoiceTest,
} from "./settings-types";

/** An answer, or a refusal a person can read; `errors` are the 400's field errors when it had them. */
export type Result<T> = { ok: true; value: T } | { ok: false; message: string; errors: FieldError[] };

export interface SettingsApi {
  settings(): Promise<Result<Settings>>;
  patchSettings(patch: SettingsPatch): Promise<Result<PatchAnswer>>;
  /** Stores the key in the Keychain and checks it. The key goes in the body only. */
  storeKey(key: string): Promise<Result<KeyAnswer>>;
  verifyKey(): Promise<Result<Verdict>>;
  models(): Promise<Result<ModelListing>>;
  voiceDevices(): Promise<Result<VoiceDevices>>;
  /** Turns the microphone loop on or off; this is what opens the microphone. */
  setVoice(enabled: boolean): Promise<Result<VoiceState>>;
  voiceTest(): Promise<Result<VoiceTest>>;
  downloads(): Promise<Result<Downloads>>;
  startDownload(what: DownloadWhat): Promise<Result<Downloads>>;
  folders(prefix: string): Promise<Result<FolderSuggestion[]>>;
  doctor(): Promise<Result<Doctor>>;
  fix(id: string): Promise<Result<FixAnswer>>;
  reset(level: ResetLevel, removeKey: boolean): Promise<Result<ResetAnswer>>;
  backups(): Promise<Result<Backup[]>>;
  restore(id: string): Promise<Result<RestoreAnswer>>;
  patchRoom(id: string, patch: RoomPatch): Promise<Result<null>>;
  removeRoom(id: string): Promise<Result<null>>;
}

export const ok = <T>(value: T): Result<T> => ({ ok: true, value });
export const refused = <T>(message: string, errors: FieldError[] = []): Result<T> => ({ ok: false, message, errors });
