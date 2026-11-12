// Copies the shared models (with the agents' figures under models/agents/) and
// textures into public/assets before dev and build.
// The copy is git-ignored; the originals live in ../assets.
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(web, "..", "assets");
const target = join(web, "public", "assets");

rmSync(target, { recursive: true, force: true });
for (const dir of ["models", "textures"]) {
  mkdirSync(join(target, dir), { recursive: true });
  cpSync(join(source, dir), join(target, dir), {
    recursive: true,
    filter: (path) => !path.split("/").pop()?.startsWith("_"),
  });
}
console.log(`assets synced to ${target}`);
