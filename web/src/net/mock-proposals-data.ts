// Mock mode's sample proposals and made tools: two tools and two changes
// waiting, a few decided, and four made tools in different states with runs.

import { HAIKU, OPUS } from "./mock-settings-data";
import type { MadeRun, MadeTool, Proposal, ProposedTool, Reach } from "./proposal-types";

const HOUR = 3600;
const DAY = 86_400;

/** Made-up hashes: 64 hex characters from a word, so each script has its own. */
export function mockHash(text: string): string {
  let h = 0x811c9dc5;
  let out = "";
  for (let round = 0; out.length < 64; round++) {
    for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i) ^ round, 0x01000193) >>> 0;
    out += h.toString(16).padStart(8, "0");
  }
  return out.slice(0, 64);
}

const ENGINE = { name: "engine", path: "/Users/you/Projects/engine" };
const SHOP = { name: "shop", path: "/Users/you/Projects/shop" };

const COUNT_LINES = `"""Count lines of code per language in the folders this tool may read.

Input: {"folder": "engine", "skip": ["node_modules", ".git"]}
Output: one line per language, largest first, and a total.
"""
import json
import os
import sys

EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".js": "JavaScript",
    ".css": "CSS",
    ".md": "Markdown",
    ".sh": "Shell",
    ".toml": "TOML",
}


def count(path):
    try:
        with open(path, "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def main():
    request = json.load(sys.stdin)
    folders = json.loads(os.environ.get("FOLDERS", "{}"))
    name = request.get("folder", "")
    if name not in folders:
        print(f"Unknown folder {name!r}; this tool may read: {', '.join(sorted(folders)) or 'none'}.")
        return 2
    skip = set(request.get("skip", ["node_modules", ".git", "dist"]))
    totals = {}
    for root, dirs, files in os.walk(folders[name]):
        dirs[:] = [d for d in dirs if d not in skip]
        for file in files:
            language = EXTENSIONS.get(os.path.splitext(file)[1])
            if language:
                totals[language] = totals.get(language, 0) + count(os.path.join(root, file))
    for language, lines in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"{language:<12} {lines:>8,}")
    print(f"{'Total':<12} {sum(totals.values()):>8,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
`;

const FEED_V1 = `#!/bin/sh
# Fetch an RSS or Atom feed and print the newest titles.
# Input: {"url": "https://example.org/feed.xml"}
set -eu
url=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')
curl -fsSL --max-time 20 "$url" | grep -o '<title>[^<]*</title>' | head -n 10 | sed 's/<[^>]*>//g'
`;

const FEED_V2 = `#!/bin/sh
# Fetch an RSS or Atom feed and print the newest titles with their dates.
# Input: {"url": "https://example.org/feed.xml", "limit": 10}
set -eu
input=$(cat)
url=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')
limit=$(printf '%s' "$input" | python3 -c 'import json,sys; print(int(json.load(sys.stdin).get("limit", 10)))')
case "$url" in
  https://*) ;;
  *) echo "Only https feeds are fetched." >&2; exit 2 ;;
esac
curl -fsSL --max-time 20 --max-filesize 2000000 "$url" \\
  | tr '\\n' ' ' \\
  | grep -o '<item>.*</item>\\|<entry>.*</entry>' \\
  | sed 's/<\\/item>/\\n/g; s/<\\/entry>/\\n/g' \\
  | sed -n 's/.*<title>\\([^<]*\\)<\\/title>.*<\\(pubDate\\|updated\\)>\\([^<]*\\)<.*/\\3  \\1/p' \\
  | head -n "$limit"
`;

const TODO_SCAN = `"""List TODO and FIXME lines in a project folder, with file and line number."""
import json
import os
import re
import sys

MARK = re.compile(r"\\b(TODO|FIXME)\\b[:\\s]*(.*)")

request = json.load(sys.stdin)
folders = json.loads(os.environ["FOLDERS"])
base = folders[request["folder"]]
found = 0
for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
    for file in files:
        path = os.path.join(root, file)
        try:
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    match = MARK.search(line)
                    if match:
                        found += 1
                        print(f"{os.path.relpath(path, base)}:{number}  {match.group(1)}  {match.group(2).strip()}")
        except (OSError, UnicodeDecodeError):
            continue
print(f"{found} found.")
`;

const CSV_CHECK = `"""Check that every row of a CSV file has the same number of columns as its header."""
import csv
import json
import os
import sys

request = json.load(sys.stdin)
folders = json.loads(os.environ["FOLDERS"])
path = os.path.join(folders[request["folder"]], request["file"])
with open(path, newline="", encoding="utf-8") as handle:
    rows = list(csv.reader(handle))
width = len(rows[0]) if rows else 0
bad = [i for i, row in enumerate(rows[1:], 2) if len(row) != width]
print(f"{len(rows) - 1} rows, {width} columns; {len(bad)} rows with another width: {bad[:20]}")
`;

const PERSONA_BEFORE = `You are Brass, the steward of the house. You keep the Library and the Control Room in order.

You answer briefly and plainly. You file what the owner dictates under the right heading, and you say where you put it. When a note contradicts an earlier one, you keep both and say which is newer.

You do not guess dates. When the owner says "next week", you ask which day.`;

const PERSONA_AFTER = `You are Brass, the steward of the house. You keep the Library and the Control Room in order.

You answer briefly and plainly. You file what the owner dictates under the right heading, and you say where you put it. When a note contradicts an earlier one, you keep both and say which is newer.

You do not guess dates. When the owner says "next week", you ask which day.

Before filing a note about a project, you look for a procedure on how that project's notes are kept, and follow it. When you find yourself doing the same filing three times, you write a procedure for it.

Every Friday you list the notes that were changed this week, grouped by project, so the owner can read them in one place.`;

const schema = (props: Record<string, unknown>, required: string[]): Record<string, unknown> => ({ type: "object", properties: props, required });

const COUNT_SCHEMA = schema({ folder: { type: "string", description: "Short name of the folder" }, skip: { type: "array", items: { type: "string" } } }, ["folder"]);
const FEED_SCHEMA = schema({ url: { type: "string" }, limit: { type: "integer", minimum: 1, maximum: 50 } }, ["url"]);
const TODO_SCHEMA = schema({ folder: { type: "string" } }, ["folder"]);
const CSV_SCHEMA = schema({ folder: { type: "string" }, file: { type: "string" } }, ["folder", "file"]);

const reach = (network: boolean, ...folders: { name: string; path: string }[]): Reach => ({ folders, network });

function toolPart(name: string, description: string, language: ProposedTool["language"], script: string, input_schema: Record<string, unknown>, r: Reach, version = 1, replaces: number | null = null): ProposedTool {
  return { name, tool_name: `made_${name}`, description, input_schema, language, script, sha256: mockHash(script), reach: r, version, replaces };
}

const base = (now: number, id: string, agent: string, agent_name: string, ago: number): Pick<Proposal, "id" | "agent" | "agent_name" | "job" | "room" | "created_at" | "decided_at" | "note" | "restored_at" | "decision"> => ({
  id,
  agent,
  agent_name,
  job: "",
  room: null,
  created_at: now - ago,
  decided_at: null,
  note: "",
  restored_at: null,
  decision: null,
});

/** Every script in the sample, by tool and version, for the made tools' versions. */
export const SCRIPTS: Record<string, Record<number, string>> = {
  todo_scan: { 1: TODO_SCAN },
  fetch_feed: { 1: FEED_V1, 2: FEED_V2 },
  csv_check: { 1: CSV_CHECK },
  count_lines: { 1: COUNT_LINES },
};

export function seedProposals(now: number): Proposal[] {
  return [
    {
      ...base(now, "a1b2c3d4", "maker", "Tink", 40 * 60),
      job: "3f2a91c0",
      room: "workshop",
      kind: "tool",
      status: "waiting",
      title: "New tool count_lines",
      reason: "I count lines by hand with find and wc in three projects every week for the size report; one tool would do it the same way each time and skip the vendored folders.",
      tool: toolPart("count_lines", "Count lines of code per language in a project folder, largest first.", "python", COUNT_LINES, COUNT_SCHEMA, reach(false, ENGINE, SHOP)),
      change: null,
    },
    {
      ...base(now, "b7e4f019", "scout", "Rook", 25 * 60),
      job: "77c0de12",
      room: "observatory",
      kind: "tool",
      status: "waiting",
      title: "New version 2 of fetch_feed",
      reason: "The first version printed the channel's own title as if it were news and had no dates. This one prints each item's date and refuses anything that is not https.",
      tool: toolPart("fetch_feed", "Fetch an RSS or Atom feed over https and print the newest items with their dates.", "sh", FEED_V2, FEED_SCHEMA, reach(true), 2, 1),
      change: null,
    },
    {
      ...base(now, "c3d9a7e2", "checker", "Tock", 12 * 60),
      kind: "change",
      status: "waiting",
      title: "Tock's model",
      reason: "Reviews of the engine's renderer keep missing the cross-file mistakes; the larger model caught both in a trial run on last week's change.",
      tool: null,
      change: { agent: "checker", agent_name: "Tock", field: "model", before: HAIKU, after: OPUS },
    },
    {
      ...base(now, "d5f1b8c6", "steward", "Brass", 5 * 60),
      kind: "change",
      status: "waiting",
      title: "Brass's persona",
      reason: "I keep doing the same filing by hand. I would like my persona to say that I look for a procedure first and write one when I repeat myself, and to give you a Friday list.",
      tool: null,
      change: { agent: "steward", agent_name: "Brass", field: "persona", before: PERSONA_BEFORE, after: PERSONA_AFTER },
    },
    {
      ...base(now, "e8a2c4d0", "envoy", "Wren", 2 * DAY),
      kind: "change",
      status: "approved",
      decided_at: now - 2 * DAY + 3 * HOUR,
      title: "Wren's thinking level",
      reason: "Drafting replies to suppliers needs more care than the default allows.",
      tool: null,
      change: { agent: "envoy", agent_name: "Wren", field: "effort", before: "medium", after: "high" },
    },
    {
      ...base(now, "f0c1d2e3", "envoy", "Wren", 3 * DAY),
      kind: "tool",
      status: "declined",
      decided_at: now - 3 * DAY + HOUR,
      note: "Not now: mail goes out through the phone, where I see it first.",
      title: "New tool send_mail",
      reason: "To send the replies I draft without asking you to copy them.",
      tool: toolPart("send_mail", "Send an email through the Mac's mail relay.", "python", "import smtplib\n", schema({ to: { type: "string" }, body: { type: "string" } }, ["to", "body"]), reach(true)),
      change: null,
    },
    {
      ...base(now, "a9b8c7d6", "maker", "Tink", 6 * DAY),
      kind: "tool",
      status: "approved",
      decided_at: now - 6 * DAY + 2 * HOUR,
      decision: { who: "author", tier: "ask" },
      title: "New tool todo_scan",
      reason: "To list what is left in a project before a release.",
      tool: toolPart("todo_scan", "List TODO and FIXME lines in a project folder.", "python", TODO_SCAN, TODO_SCHEMA, reach(false, ENGINE, SHOP)),
      change: null,
    },
    {
      ...base(now, "b1a2c3d4", "scout", "Rook", 9 * DAY),
      kind: "tool",
      status: "approved",
      decided_at: now - 9 * DAY + HOUR,
      decision: { who: "everyone", tier: "ask" },
      title: "New tool fetch_feed",
      reason: "To read the news feeds you follow without opening a browser.",
      tool: toolPart("fetch_feed", "Fetch an RSS or Atom feed and print the newest titles.", "sh", FEED_V1, FEED_SCHEMA, reach(true)),
      change: null,
    },
    {
      ...base(now, "c4b3a2d1", "checker", "Tock", 12 * DAY),
      kind: "tool",
      status: "approved",
      decided_at: now - 12 * DAY + HOUR,
      decision: { who: "author", tier: "free" },
      title: "New tool csv_check",
      reason: "The shop's exports break when a row has a stray comma; I check them before each import.",
      tool: toolPart("csv_check", "Check that every row of a CSV file has as many columns as its header.", "python", CSV_CHECK, CSV_SCHEMA, reach(false, SHOP)),
      change: null,
    },
  ];
}

const version = (name: string, n: number, approved_at: number, proposal: string): MadeTool["versions"][number] => ({
  version: n,
  sha256: mockHash(SCRIPTS[name]?.[n] ?? name),
  approved_at,
  proposal,
});

export function seedMadeTools(now: number): MadeTool[] {
  return [
    {
      name: "todo_scan",
      tool_name: "made_todo_scan",
      description: "List TODO and FIXME lines in a project folder.",
      language: "python",
      author: "maker",
      author_name: "Tink",
      reason: "To list what is left in a project before a release.",
      input_schema: TODO_SCHEMA,
      reach: reach(false, ENGINE, SHOP),
      who: "author",
      tier: "ask",
      enabled: true,
      status: "enabled",
      disabled_reason: "",
      version: 1,
      sha256: mockHash(TODO_SCAN),
      versions: [version("todo_scan", 1, now - 6 * DAY + 2 * HOUR, "a9b8c7d6")],
      created_at: now - 6 * DAY + 2 * HOUR,
      runs: 3,
      last_run: { ts: now - 2 * HOUR, agent: "maker", exit_code: 0, ok: true },
    },
    {
      name: "fetch_feed",
      tool_name: "made_fetch_feed",
      description: "Fetch an RSS or Atom feed and print the newest titles.",
      language: "sh",
      author: "scout",
      author_name: "Rook",
      reason: "To read the news feeds you follow without opening a browser.",
      input_schema: FEED_SCHEMA,
      reach: reach(true),
      who: "everyone",
      tier: "ask",
      enabled: false,
      status: "pending",
      disabled_reason: "A new version waits for your decision in Proposals.",
      version: 1,
      sha256: mockHash(FEED_V1),
      versions: [version("fetch_feed", 1, now - 9 * DAY + HOUR, "b1a2c3d4")],
      created_at: now - 9 * DAY + HOUR,
      runs: 11,
      last_run: { ts: now - DAY, agent: "scout", exit_code: 0, ok: true },
    },
    {
      name: "csv_check",
      tool_name: "made_csv_check",
      description: "Check that every row of a CSV file has as many columns as its header.",
      language: "python",
      author: "checker",
      author_name: "Tock",
      reason: "The shop's exports break when a row has a stray comma; I check them before each import.",
      input_schema: CSV_SCHEMA,
      reach: reach(false, SHOP),
      who: "author",
      tier: "free",
      enabled: false,
      status: "changed",
      disabled_reason: "Its script changed on disk after you approved it, so it was turned off. Go back to an approved version to use it again.",
      version: 1,
      sha256: mockHash(CSV_CHECK),
      versions: [version("csv_check", 1, now - 12 * DAY + HOUR, "c4b3a2d1")],
      created_at: now - 12 * DAY + HOUR,
      runs: 6,
      last_run: { ts: now - 3 * DAY, agent: "checker", exit_code: 1, ok: false },
    },
  ];
}

const run = (now: number, ago: number, agent: string, agent_name: string, v: number, sha: string, input: string, exit_code: number | null, seconds: number, output: string): MadeRun => ({
  ts: now - ago,
  agent,
  agent_name,
  job: "3f2a91c0",
  version: v,
  sha256: sha,
  input,
  exit_code,
  seconds,
  output,
  truncated: false,
  swept: 0,
});

export function seedRuns(now: number): Record<string, MadeRun[]> {
  const todo = mockHash(TODO_SCAN);
  const feed = mockHash(FEED_V1);
  const csv = mockHash(CSV_CHECK);
  return {
    todo_scan: [
      run(now, 2 * HOUR, "maker", "Tink", 1, todo, '{"folder": "engine"}', 0, 0.84, "src/render/pass.ts:41  TODO  batch the shadow casters\nsrc/io/csv.ts:12  FIXME  day and month swap on import\n2 found."),
      run(now, DAY, "maker", "Tink", 1, todo, '{"folder": "shop"}', 0, 1.12, "checkout/tax.py:88  TODO  rounding for CHF\n1 found."),
      run(now, 4 * DAY, "maker", "Tink", 1, todo, '{"folder": "engine"}', 0, 0.91, "src/io/csv.ts:12  FIXME  day and month swap on import\n1 found."),
    ],
    fetch_feed: [
      run(now, DAY, "scout", "Rook", 1, feed, '{"url": "https://example.org/feed.xml"}', 0, 1.9, "Example News\nThe renderer ships\nA quieter week"),
      run(now, 2 * DAY, "host", "Vision", 1, feed, '{"url": "https://example.org/slow.xml"}', null, 20, "Stopped at the time limit (20 s)."),
    ],
    csv_check: [run(now, 3 * DAY, "checker", "Tock", 1, csv, '{"folder": "shop", "file": "exports/orders.csv"}', 1, 0.31, "Traceback (most recent call last):\n  File \"<string>\", line 9, in <module>\nFileNotFoundError: exports/orders.csv")],
  };
}
