// Narrowing the local-model routes' JSON and the `brain.mode` event to their
// types, or null when the shape is wrong.

import type { BrainMode, CustomModel, DeleteAnswer, LocalChosen, LocalDownload, LocalListing, LocalModelRow, ServerTest } from "./brain-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const orNull = (is: (v: unknown) => boolean) => (v: unknown): boolean => v === null || is(v);
const oneOf =
  (...values: string[]) =>
  (v: unknown): boolean =>
    typeof v === "string" && values.includes(v);
const listOf = (is: (v: unknown) => boolean) => (v: unknown): boolean => Array.isArray(v) && v.every(is);

function isDownload(v: unknown): v is LocalDownload {
  return isObj(v) && oneOf("idle", "running", "done", "failed")(v["state"]) && isNum(v["done_bytes"]) && orNull(isNum)(v["total_bytes"]) && orNull(isStr)(v["message"]);
}

function isRow(v: unknown): v is LocalModelRow {
  return (
    isObj(v) &&
    isStr(v["id"]) &&
    isStr(v["title"]) &&
    isStr(v["good_at"]) &&
    isStr(v["kind"]) &&
    isNum(v["params_b"]) &&
    isNum(v["size_bytes"]) &&
    isNum(v["memory_gb"]) &&
    isNum(v["context"]) &&
    isBool(v["tools"]) &&
    isBool(v["tools_recommended"]) &&
    isStr(v["license"]) &&
    oneOf("comfortable", "tight", "too_big")(v["fit"]) &&
    orNull(isNum)(v["on_disk_bytes"]) &&
    isDownload(v["download"])
  );
}

function isCustom(v: unknown): v is CustomModel {
  return isObj(v) && isStr(v["id"]) && orNull(isNum)(v["on_disk_bytes"]) && isDownload(v["download"]);
}

function isChosen(v: unknown): v is LocalChosen {
  return isObj(v) && isStr(v["backend"]) && isStr(v["model"]) && isStr(v["server"]) && orNull(isBool)(v["tools"]);
}

export function asLocalListing(v: unknown): LocalListing | null {
  const ok =
    isObj(v) &&
    isStr(v["taken"]) &&
    isNum(v["memory_bytes"]) &&
    orNull(isStr)(v["recommended"]) &&
    listOf(isRow)(v["models"]) &&
    isChosen(v["chosen"]) &&
    orNull(isCustom)(v["custom"]) &&
    isBool(v["offline"]);
  return ok ? (v as unknown as LocalListing) : null;
}

export function asDeleteAnswer(v: unknown): DeleteAnswer | null {
  return asLocalListing(v) !== null && isObj(v) && isStr(v["deleted"]) && isNum(v["freed_bytes"]) ? (v as unknown as DeleteAnswer) : null;
}

export function asServerTest(v: unknown): ServerTest | null {
  return isObj(v) && isBool(v["ok"]) && listOf(isStr)(v["models"]) && isStr(v["message"]) ? (v as unknown as ServerTest) : null;
}

export function asBrainMode(v: unknown): BrainMode | null {
  const ok =
    isObj(v) &&
    isBool(v["offline"]) &&
    oneOf("claude", "local", "fake")(v["answering"]) &&
    isStr(v["local_backend"]) &&
    isStr(v["local_model"]) &&
    orNull(isBool)(v["local_tools"]) &&
    (v["local_images"] === undefined || isBool(v["local_images"])) &&
    (v["local_state"] === undefined || oneOf("unloaded", "loading", "ready", "failed")(v["local_state"])) &&
    (v["local_bytes"] === undefined || orNull(isNum)(v["local_bytes"])) &&
    (v["local_cache_bytes"] === undefined || isNum(v["local_cache_bytes"])) &&
    (v["local_reading"] === undefined || orNull((r) => Array.isArray(r) && r.length === 2 && r.every(isNum))(v["local_reading"])) &&
    (v["local_problem"] === undefined || orNull(isStr)(v["local_problem"]));
  return ok ? (v as unknown as BrainMode) : null;
}
