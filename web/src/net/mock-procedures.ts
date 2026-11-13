// Mock mode's procedures: two of Tink's, one of Brass's and two shared, kept
// and checked the way vision/procedures does, each change announced with
// `procedure.changed`.

import type { ProceduresApi } from "./procedures-api";
import { SHARED, type Procedure, type ProcedureEdit, type ProcedureListing } from "./procedure-types";
import { ok, refused, type Result } from "./settings-api";
import type { OutboundData, OutboundType, Plan } from "./types";

export const MOCK_PROCEDURE_LIMITS = { name: 80, when: 300, steps: 6000, per_agent: 40, shared: 60 };

/** What the mock procedures need from the mock daemon. */
export interface MockProceduresHost {
  emit<K extends OutboundType>(type: K, data: OutboundData[K]): void;
  plan(): Plan;
}

interface Kept {
  owner: string;
  procedure: Procedure;
}

const DAY = 86_400;
const now = (): number => Date.now() / 1000;

function made(owner: string, name: string, title: string, when: string, author: string, ago: number, opened: number, steps: string): Kept {
  return { owner, procedure: { name, title, when, author, shared: owner === SHARED, changed_at: now() - ago, opened, chars: steps.length, steps } };
}

function seed(): Kept[] {
  return [
    made(
      "maker",
      "release-the-shop-app",
      "Release the shop app",
      "Before tagging a release of the shop project.",
      "maker",
      2 * DAY,
      3,
      "1. Run the tests in ~/Projects/shop with `npm test -- --run`; stop if any fail.\n2. Read CHANGELOG.md and add the release's lines under a new heading with today's date.\n3. Bump the version in package.json (patch for fixes, minor for features).\n4. Ask the owner before tagging: say the version and the three most important changes.\n5. Tag with `git tag v<version>` and push the tag only after the owner says yes.",
    ),
    made(
      "maker",
      "fix-a-date-format-bug",
      "Fix a date format bug",
      "When a report or an import shows the day and the month swapped.",
      "maker",
      5 * DAY,
      1,
      "1. Find the parser: search for `parseDate` and `strptime`.\n2. Write a failing test with 03/04/2026 read as 3 April.\n3. Fix the format string, never the data.\n4. Run the whole suite, then ask Tock to check the change.",
    ),
    made(
      "steward",
      "file-a-dictated-note",
      "File a dictated note",
      "When the owner dictates a note about a project.",
      "steward",
      DAY,
      7,
      "1. Find the project's heading in the Library; make one if there is none.\n2. Put the date first, then the note in the owner's words.\n3. If it contradicts an earlier note, keep both and say which is newer.\n4. Say where it went in one sentence.",
    ),
    made(
      SHARED,
      "hand-work-to-another-resident",
      "Hand work to another resident",
      "When a job needs a skill another resident has.",
      "host",
      9 * DAY,
      12,
      "1. Say in one line what you need and why.\n2. Name the room whose project it is about.\n3. Wait for the answer before going on with the part that depends on it.",
    ),
    made(
      SHARED,
      "ask-before-anything-irreversible",
      "Ask before anything irreversible",
      "Before deleting, sending, publishing or paying for anything.",
      "steward",
      14 * DAY,
      21,
      "1. Stop.\n2. Say exactly what will happen and that it cannot be undone.\n3. Go on only after the owner says yes in this conversation.",
    ),
  ];
}

const no = <T>(message: string): Promise<Result<T>> => Promise.resolve(refused(message));

export class MockProcedures implements ProceduresApi {
  private items: Kept[] = seed();

  constructor(private readonly host: MockProceduresHost) {}

  list(): Promise<Result<ProcedureListing>> {
    const byTitle = (a: Kept, b: Kept): number => a.procedure.title.localeCompare(b.procedure.title);
    const strip = ({ procedure }: Kept): Omit<Procedure, "steps"> => {
      const { steps: _, ...rest } = procedure;
      return rest;
    };
    const agents = this.host.plan().agents.map((a) => ({
      id: a.id,
      name: a.name,
      procedures: this.items.filter((k) => k.owner === a.id).sort(byTitle).map(strip),
    }));
    const shared = this.items.filter((k) => k.owner === SHARED).sort(byTitle).map(strip);
    return Promise.resolve(ok(structuredClone({ agents, shared, limits: MOCK_PROCEDURE_LIMITS })));
  }

  get(owner: string, name: string): Promise<Result<Procedure>> {
    const kept = this.find(owner, name);
    return kept ? Promise.resolve(ok(structuredClone(kept.procedure))) : no(`There is no procedure '${name}' for ${owner}.`);
  }

  edit(owner: string, name: string, edit: ProcedureEdit): Promise<Result<Procedure>> {
    const kept = this.find(owner, name);
    if (!kept) return no(`There is no procedure '${name}' for ${owner}.`);
    if (edit.title === undefined && edit.when === undefined && edit.steps === undefined) return no("Give a new title, when to use it, or new steps.");
    const L = MOCK_PROCEDURE_LIMITS;
    const title = edit.title === undefined ? kept.procedure.title : line(edit.title, "a title", L.name);
    const when = edit.when === undefined ? kept.procedure.when : line(edit.when, "when to use it", L.when);
    const steps = edit.steps === undefined ? kept.procedure.steps : edit.steps.trim();
    for (const problem of [title, when]) if (problem instanceof Error) return no(problem.message);
    if (!steps) return no("The procedure needs its steps.");
    if (steps.length > L.steps) return no(`The steps must be at most ${L.steps} characters; they have ${steps.length}.`);
    kept.procedure = { ...kept.procedure, title: title as string, when: when as string, steps, chars: steps.length, changed_at: now() };
    this.host.emit("procedure.changed", { owner, name, change: "saved" });
    return Promise.resolve(ok(structuredClone(kept.procedure)));
  }

  remove(owner: string, name: string): Promise<Result<true>> {
    if (!this.find(owner, name)) return no(`There is no procedure '${name}' for ${owner}.`);
    this.items = this.items.filter((k) => !(k.owner === owner && k.procedure.name === name));
    this.host.emit("procedure.changed", { owner, name, change: "removed" });
    return Promise.resolve(ok(true as const));
  }

  private find(owner: string, name: string): Kept | undefined {
    return this.items.find((k) => k.owner === owner && k.procedure.name === name);
  }
}

/** One line of text, spaces folded, within its limit; an Error says why not, as the daemon says it. */
function line(value: string, what: string, most: number): string | Error {
  const text = value.split(/\s+/).filter(Boolean).join(" ");
  if (!text) return new Error(`The procedure needs ${what}.`);
  if (text.length > most) return new Error(`${what.charAt(0).toUpperCase()}${what.slice(1)} must be at most ${most} characters; it has ${text.length}.`);
  return text;
}
