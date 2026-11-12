// The settings routes over HTTP, with the token header from Api. Nothing
// secret goes in a URL: the key travels in a POST body only.

import type { Api } from "./api";
import { ok, refused, type Result, type SettingsApi } from "./settings-api";
import {
  asBackups,
  asDoctor,
  asDownloads,
  asFixAnswer,
  asFolders,
  asKeyAnswer,
  asModelListing,
  asPatchAnswer,
  asResetAnswer,
  asRestoreAnswer,
  asSettings,
  asVerdict,
  asVoiceDevices,
  asVoiceState,
  asVoiceTest,
} from "./settings-guards";
import type { DownloadWhat, ResetLevel, RoomPatch, SettingsPatch } from "./settings-types";

const SHAPE = "The answer was not in the expected shape.";

/** The query for `GET /api/fs/dirs`, or null when the text cannot name a folder yet. */
export function foldersQuery(text: string): string | null {
  const prefix = text.trim();
  if (!prefix.startsWith("/") && !prefix.startsWith("~")) return null;
  return `/api/fs/dirs?${new URLSearchParams({ prefix })}`;
}

export class HttpSettings implements SettingsApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    if (!answer.ok) return answer;
    const value = narrow(answer.value);
    return value === null ? refused(SHAPE) : ok(value);
  }

  settings = () => this.ask("GET", "/api/settings", asSettings);
  patchSettings = (patch: SettingsPatch) => this.ask("PATCH", "/api/settings", asPatchAnswer, patch);
  storeKey = (key: string) => this.ask("POST", "/api/settings/key", asKeyAnswer, { key });
  verifyKey = () => this.ask("POST", "/api/settings/key/verify", asVerdict);
  models = () => this.ask("GET", "/api/models", asModelListing);
  voiceDevices = () => this.ask("GET", "/api/voice/devices", asVoiceDevices);
  setVoice = (enabled: boolean) => this.ask("POST", "/api/voice", asVoiceState, { enabled });
  voiceTest = () => this.ask("POST", "/api/voice/test", asVoiceTest);
  downloads = () => this.ask("GET", "/api/downloads", asDownloads);
  startDownload = (what: DownloadWhat) => this.ask("POST", "/api/downloads", asDownloads, { what });
  doctor = () => this.ask("GET", "/api/doctor", asDoctor);
  fix = (id: string) => this.ask("POST", "/api/doctor/fix", asFixAnswer, { id });
  reset = (level: ResetLevel, removeKey: boolean) => this.ask("POST", "/api/reset", asResetAnswer, { level, remove_key: removeKey });
  backups = () => this.ask("GET", "/api/backups", asBackups);
  restore = (id: string) => this.ask("POST", `/api/backups/${encodeURIComponent(id)}/restore`, asRestoreAnswer);
  patchRoom = (id: string, patch: RoomPatch) => this.ask("PATCH", roomPath(id), accepted, patch).then(asDone);
  removeRoom = (id: string) => this.ask("DELETE", roomPath(id), accepted).then(asDone);

  folders(prefix: string): ReturnType<SettingsApi["folders"]> {
    const path = foldersQuery(prefix);
    if (path === null) return Promise.resolve(refused("A folder starts with / or ~."));
    return this.ask("GET", path, asFolders);
  }
}

const roomPath = (id: string): string => `/api/house/rooms/${encodeURIComponent(id)}`;

/** Room routes answer the new revision; the plan arrives by `house.changed`, so only success matters. */
const accepted = (): true => true;
const asDone = (r: Result<true>): Result<null> => (r.ok ? ok(null) : r);
