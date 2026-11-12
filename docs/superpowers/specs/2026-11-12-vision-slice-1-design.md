# Vision, slice 1: talk to Vision in the house

Date: 2026-11-12
Status: awaiting review
Design board: Paper file "Vision PRO AI", page "Plan", boards 01 to 05

## 1. What Vision is

Vision is a personal assistant that runs all the time on one Mac, for one person. A Python daemon is the mind. A fullscreen 3D mansion, seen from above with the roof off, is the face. Vision sits in the Hall and talks with you by voice or text. Later slices move other residents into the other rooms, each with its own memory and personality, and give them hands.

Vision's own mind runs on the Anthropic API, paid from the promotional credits granted each month. It does not use the Claude Max login at all, which removes the question of whether scripted use fits the subscription terms and keeps Vision off the Max usage limits. Speech recognition and speech run locally and cost nothing. A local model stands behind Claude as the fallback. ChatGPT and Gemini subscriptions stay available for specific residents in later slices.

### Decisions already made

| Decision | Choice |
|---|---|
| First slice | Core daemon, the 3D house, text and voice with Vision |
| Language | English |
| Cast | Six original agents: Vision (host), Brass (steward), Wren (envoy), Tink (maker), Tock (checker), Rook (scout, in the tower). All renameable |
| Autonomy | Ask before risky actions |
| Approach | Python core, WebGL house in a native fullscreen window |
| Look | Board 04: cutaway mansion at dusk, warm rooms, oxblood panel, mustard chair |
| Rendering | Fully modelled 3D house, not a painting |
| Assets | Meshy for models, Higgsfield for textures |
| Claude access | Anthropic API on the monthly promotional credits, not the Max login |
| Talk model | `claude-haiku-5-5`, for speed and cost |
| Heavy model | `claude-opus-5-5`, when asked to think something through |
| Speech | Local models: Whisper in, Kokoro out |
| House | Modular grid. Default rooms plus up to 20 more, placed where you choose |
| Agents | Predefined in config, each with its own persona and model |
| Open source | Planned, under the name OpenQuestAI. The repo ships neutral defaults; your cast, projects and memory live in `~/.vision/` |

### The whole system, in six slices

1. **Talk** (this spec). Daemon, house, Vision, voice, memory, gate.
2. **The House.** Residents and project rooms, delegation, Codex and Gemini as brains.
3. **Workshop.** Build and render prototypes, apps and 3D objects inside the house.
4. **Hands.** Mac control and data access, all through the gate.
5. **Remote.** The house on the phone over a private network, Telegram for pushes.
6. **Routines.** Briefings, check-ins, background jobs.

Each later slice gets its own spec. Nothing in this spec builds for them beyond the interfaces named in section 4.

## 2. Slice 1 scope

### Done when

1. After login the daemon is running without anyone starting it, and it comes back by itself if killed.
2. `vision ui` opens a fullscreen window showing the 3D mansion. You can orbit it, and double-clicking a room flies the camera into it.
3. You say "Hey Vision" and ask a question. Vision answers aloud, the caption shows both sides, and the Hall reacts while it speaks. Target: speech begins within about three seconds of you finishing. This is a target to measure, not a promise.
4. You can type instead of talking and get the same answer path.
5. You can interrupt Vision mid-sentence by holding Space or saying "Vision, stop".
6. Vision remembers a fact across a daemon restart ("my DCF release is on Friday").
7. Asking Vision to run a shell command produces a card that needs your yes. Yes runs it, no does not, and both are in the audit log.
8. With the network off, Vision still answers through the local model and says it is running locally.
9. The house shows this month's API spend against the cap. When the cap is reached, talk moves to the local model by itself.
10. Adding a room, by clicking a free slot in the house or by editing `house.toml`, makes it appear without a restart, with walls and doors redrawn around it. A 21st extra room is refused with a clear message.

### Out of scope

Other residents, delegation, Codex and Gemini, the Workshop, any Mac control beyond `open_app`, `open_url` and `shell` (section 4.5), messaging, routines, and furniture for rooms other than the Hall.

## 3. Architecture

```
            faces                         core (Python daemon)                brains
  ┌──────────────────────┐   WebSocket   ┌───────────────────────┐        ┌─────────────┐
  │ Mindspace window     │◄─────────────►│ server  ── event bus  │───────►│ Claude API  │
  │ (Three.js + HUD)     │               │ Vision session        │        │ (primary)   │
  └──────────────────────┘               │ router ─ gate ─ memory│───────►│ Local model │
  ┌──────────────────────┐   in process  │ voice loop ─ budget   │        │ (fallback)  │
  │ microphone, speakers │◄─────────────►│                       │        └─────────────┘
  └──────────────────────┘               └───────────────────────┘
```

Two processes. The **daemon** is headless and always on. The **window** is a thin shell that shows the web app the daemon serves; closing it does not stop Vision, and voice keeps working without it.

Everything inside the daemon talks through one async event bus. The WebSocket is that bus, filtered, sent to the window.

## 4. Components

Each unit has one job and a small interface. Paths are relative to the repo root.

### 4.1 Core: `vision/core/`

| File | Job |
|---|---|
| `events.py` | Typed event classes and the JSON envelope. The single source of truth for section 5. |
| `bus.py` | Async publish and subscribe. `publish(event)`, `subscribe(types) -> AsyncIterator`. |
| `config.py` | Loads `~/.vision/config.toml` over built-in defaults. |
| `server.py` | FastAPI app: static web files, `/api/*`, `/ws`. |
| `session.py` | One conversation turn end to end: input, brain, sentences, voice, log. |
| `cli.py` | `vision run`, `vision ui`, `vision auth`, `vision install`, `vision uninstall`, `vision status`. |
| `launchd.py` | Writes and loads the LaunchAgent plist with `KeepAlive` and `RunAtLoad`. |

Runtime data lives in `~/.vision/`: `config.toml`, `token`, `log.db`, `logs/`, and `house/` (the memory vault). Nothing personal is written into the repo.

The server binds to `127.0.0.1` only. Every WebSocket and API call must carry the token from `~/.vision/token` (mode 0600), and the server rejects requests whose `Origin` is not its own. This stops another web page on the Mac from driving Vision.

### 4.2 Brains: `vision/brains/`

```python
class Brain(Protocol):
    name: str
    async def start(self) -> None: ...
    def send(self, text: str) -> AsyncIterator[BrainEvent]: ...   # TextDelta | ToolCall | TurnDone | BrainError
    async def interrupt(self) -> None: ...
    async def close(self) -> None: ...
```

- `claude.py`. Calls the Anthropic API directly through the official `anthropic` Python SDK, streaming. This is the path the monthly promotional credits cover (they apply to "API" and "Agent SDK"), and it is the fastest route because nothing sits between Vision and the model. The system prompt is Vision's persona plus the memory core, cached so repeat turns cost less. The only tools are the five in 4.5, and each call passes through the gate before it runs.
  - Talk model `claude-haiku-5-5`, with thinking effort set low so replies start quickly. At list price (0.10 dollars per million input tokens, 0.50 per million output) a spoken turn of roughly 4,000 tokens in and 150 out costs about a twentieth of a cent. That figure is an estimate from those assumptions, and the live check measures the real one.
  - Heavy model `claude-opus-5-5`, used when you ask Vision to think something through.
  - Both are one line each in `config.toml`.
- `local.py`. A model on this Mac through Ollama, default `qwen3.8:27b-mlx`, no tools. It speaks the OpenAI-compatible chat format, so pointing it at OpenRouter or LM Studio is a config change and needs no new code.
- `fake.py`. Scripted brain for tests.
- `router.py`. Sends each turn to Claude. On a rate limit, auth failure, exhausted credits, timeout or no network it retries once, then switches to the local model, publishes `brain.fallback`, and tries Claude again after a cool-down.
- `budget.py`. Adds up what each reply cost from the token counts the API returns and a price table in `config.toml`. The monthly cap defaults to 150 dollars. Vision gives a notice at 80 percent. At the cap, talk moves to the local model until the month turns or you raise the cap.

**Credentials.** Vision looks for the Anthropic API key in two places, in this order: the macOS Keychain, then `ANTHROPIC_API_KEY` in a git-ignored `.env` file in the project, which is the name the Anthropic SDK itself expects. `vision auth` moves a key into the Keychain if you prefer that. The key never goes into the repo, a log, a prompt or the window, and nobody but you handles it.

**Later slices.** Residents that work inside your repos will use the Claude Agent SDK on the same credits. Codex and Gemini stay available as subscription-based brains for Tock and Rook, and their terms get checked when slice 2 is specced.

### 4.3 Voice: `vision/voice/`

| File | Job |
|---|---|
| `audio_io.py` | Microphone capture and speaker playback (16 kHz mono in). |
| `vad.py` | Silero VAD. Cuts speech into utterances; 600 ms of silence ends one. |
| `stt.py` | Whisper on MLX, local. |
| `wake.py` | Decides whether an utterance is addressed to Vision. |
| `tts.py` | Kokoro, local, one sentence at a time. Falls back to macOS `say`. |
| `loop.py` | State machine: idle, listening, transcribing, thinking, speaking. |

An utterance reaches Vision when any of these is true: it starts with "hey vision" or "vision" (matched on the local transcript, tolerant of small errors), Space is held in the window, or it arrives within 20 seconds of Vision finishing a reply. That last rule lets a conversation flow without repeating the wake phrase.

While Vision is speaking, the microphone is only checked for "vision stop", "stop" or "cancel", and anything matching the sentence being spoken is discarded so Vision does not hear itself. Holding Space always interrupts.

Replies are spoken sentence by sentence as they stream, so audio starts on the first sentence. A short sound and a state change mark the moment Vision starts thinking.

The pipeline can also run from a WAV file and write its speech to a WAV file. That is how it is tested without a person at the microphone.

### 4.4 Memory: `vision/memory/`

- `vault.py`. Plain Markdown under `~/.vision/house/`. `vision/persona.md` is who Vision is. `vision/notes/*.md` is what Vision has learned. `library/*.md` is shared knowledge about you and your projects. You can read and edit all of it by hand.
- `log.py`. SQLite at `~/.vision/log.db`: `turns` (every exchange), `audit` (every tool call and gate decision), with FTS5 search over turns and notes.
- `core.py`. Builds the memory core that goes into the system prompt: persona, the library, and the most recent notes, within a fixed size budget.

The repo ships a generic starter persona and an empty library template. They are copied to `~/.vision/house/` on first run and never overwritten. Anything personal, including what is known about your own projects, is written only under `~/.vision/` and never into the repo.

### 4.5 Tools and the gate: `vision/gate/`

Slice 1 gives Vision five tools:

| Tool | Tier | What it does |
|---|---|---|
| `remember(text)` | free | Appends a note to Vision's notes. |
| `recall(query)` | free | Searches notes and past turns. |
| `open_app(name)` | free | Opens a Mac app. |
| `open_url(url)` | free | Opens a link in the default browser. |
| `shell(command)` | ask | Runs a shell command. Always asks in slice 1. |

`policy.py` maps a tool call to `free`, `ask` or `never`. `gate.py` enforces it: an `ask` publishes `gate.request`, waits up to 60 seconds for `gate.decision` from the window or a spoken yes or no, and denies on timeout. Every call and decision is written to `audit`. Tiers are data in `config.toml`, so later slices add tools without touching the gate.

### 4.6 The Mindspace: `web/`

Vite, TypeScript, Three.js. Built to static files that the daemon serves.

- `scene/house.ts`. Builds the mansion from the plan served at `/api/house` (section 4.8): floors per room, walls along every cell edge where two different rooms or the outside meet, door gaps, materials, a lamp and a camera preset per room. Walls are cut low so every room is visible from above, as on board 04. When `house.changed` arrives it rebuilds, and a new room rises into place.
- `scene/build.ts`. Build mode: free slots glow, clicking one opens a short form (name, agent, project folder, model) and posts the new room.
- `scene/props.ts`. Loads GLB furniture and characters and places them from the plan.
- `scene/lighting.ts`. Dusk ambient and a low moon. Each room has its own warm lamp whose brightness follows the room's state: dark, idle or active.
- `scene/camera.ts`. Default isometric view of the whole house, orbit and zoom within limits, fly-to-room on double-click, Escape to return.
- `scene/post.ts`. Bloom, soft depth of field for the miniature look, film grain, vignette, and the vertical signal streaks, which move with Vision's voice.
- `hud/`. The overlay from board 04: wordmark and state, residents list, room labels, the caption with your words and Vision's, the gate card, and a text field opened with `/`.
- `net/socket.ts`. The WebSocket client and a small store the HUD and scene both read.

`vision ui` opens this in a frameless fullscreen `pywebview` window. It reads `~/.vision/token` and hands it to the page through the window's script bridge, so the token never appears in a URL. `vision ui --browser` opens the same app in a normal browser for development and passes the token in the URL fragment, which is not sent to any server.

### 4.7 Assets: `assets/`

**House shell.** Built in code from the plan, so it costs nothing to change and grows as rooms are added. The default is nine rooms with the Hall at the centre, plus a round turret Attic, matching board 03.

**Textures.** Wallpaper, teal panelling, wood floor, red carpet, pale stone. Generated with Higgsfield as tileable images.

**Hall furniture, from Meshy.** Mustard wingback armchair, floor lamp, staircase, side table, framed painting, cabinet. Game-prop settings (smart topology with a texture), about 15 credits each.

**Vision.** One original stylised figure in a pale pinstripe suit, rigged, with four animations from Meshy's library: seated idle, seated talking, sit to stand, walk to sit. It is an original design and not a likeness of any actor or of any existing character.

**Cost.** About 120 Meshy credits planned out of the 1,200 available. The exact list, model choice and cost are shown for a yes before anything is generated, and again if retries would pass 200. Higgsfield cost is shown the same way.

Rooms other than the Hall are lit shells in this slice. They get furniture when their resident moves in.

### 4.8 A house that grows: `vision/house/`

The house is a set of room modules on a square grid. This package owns the house file, validates it, works out doors and free slots, and serves the plan the window draws from.

**Two files.** `house/default.toml` in the repo holds the default: six agents with the ids `host`, `steward`, `envoy`, `maker`, `checker` and `scout`, shown as Vision, Brass, Wren, Tink, Tock and Rook, and the default rooms. `~/.vision/house.toml` is yours and overrides it: your agent names, your projects, your extra rooms. On first run it is created from the default.

```toml
[agents.host]
name = "Vision"
persona = "agents/host.md"
model = "claude-haiku-5-5"
heavy_model = "claude-opus-5-5"

[agents.maker]
name = "Tink"
persona = "agents/maker.md"
model = "claude-opus-5-5"

[[rooms]]
id = "hall"
name = "Hall"
at = [1, 1]          # grid cell of the room's north-west corner
size = [2, 2]        # cells wide, cells deep; default [1, 1]
agent = "host"

[[rooms]]
id = "garage"
name = "Garage"
at = [0, 3]
agent = "maker"                          # which predefined agent runs this room
project = "~/Projects/my-platform"       # optional project folder attached to the room
model = "claude-sonnet-5-5"              # optional, overrides the agent's model here
```

**Rules.**
- Every agent has a model. A room may override it. A room names exactly one agent.
- Default rooms are the Hall, the eight rooms around it and the round Attic. They can be renamed and reassigned but not removed.
- Up to 20 extra rooms. An extra room is one to four cells, must share a wall with a room already in the house, and may not overlap another.
- If `at` is left out, the room goes into the free slot nearest the Hall.
- Removing an extra room is refused if it would cut another room off from the Hall.
- Doors are worked out, not configured: every room gets a door on the shortest path toward the Hall.

**The plan** returned by `GET /api/house`:

```json
{
  "revision": 3,
  "cell_m": 4.0,
  "wall_height_m": 2.6,
  "max_extra_rooms": 20,
  "assistant": {"name": "Vision"},
  "agents": [{"id": "host", "name": "Vision", "model": "claude-haiku-5-5", "heavy_model": "claude-opus-5-5"}],
  "rooms": [{"id": "hall", "name": "Hall", "kind": "default", "shape": "rect", "at": [1, 1], "size": [2, 2],
             "agent": "host", "model": "claude-haiku-5-5", "project": null,
             "floor": "red-carpet", "wall": "teal-panel", "state": "idle"}],
  "doors": [{"a": "hall", "b": "library", "cell": [1, 1], "side": "n"}],
  "free_slots": [[4, 1], [4, 2]]
}
```

`kind` is `default` or `extra`. `shape` is `rect` or `round` (the Attic). `model` on a room is already resolved, so the window never repeats the override logic. `floor` and `wall` name files in `assets/textures/`.

**Routes**, all behind the token: `GET /api/house`, `POST /api/house/rooms`, `PATCH /api/house/rooms/{id}`, `DELETE /api/house/rooms/{id}`. A change writes `~/.vision/house.toml`, raises the revision and publishes `house.changed`. Editing the file by hand does the same within a couple of seconds.

**In this slice** only the Host agent is awake. The other agents and their models are stored and shown in the house, and slice 2 puts them to work. Other packages read an agent's models through `vision.house.agent_models(config, agent_id)`.

## 5. Protocol

One JSON envelope in both directions: `{"type": "...", "ts": 1731400000.0, "data": {...}}`.

**Daemon to window**

| Type | Data |
|---|---|
| `state.changed` | `state`: idle, listening, transcribing, thinking, speaking; `brain`: claude or local |
| `budget` | `month`, `spent_usd`, `cap_usd` |
| `house.changed` | `revision` (the window then reloads `/api/house`) |
| `user.utterance` | `text`, `source`: voice or text |
| `vision.delta` | `text` (a streamed fragment) |
| `vision.reply` | `text` (the finished reply), `turn_id` |
| `voice.level` | `level` 0 to 1, about 30 times a second while speaking |
| `room.state` | `room`, `state`: dark, idle, active |
| `gate.request` | `id`, `tool`, `summary`, `detail`, `expires_at` |
| `gate.resolved` | `id`, `decision`: allow, deny, timeout |
| `brain.fallback` | `from`, `to`, `reason` |
| `notice` | `level`: info, warn, error; `text` |

**Window to daemon**

| Type | Data |
|---|---|
| `hello` | `token` (must be the first message) |
| `input.text` | `text` |
| `input.ptt` | `down`: true or false |
| `input.interrupt` | none |
| `gate.decision` | `id`, `decision`: allow or deny |

**HTTP.** `GET /api/health`, `GET /api/state`, `GET /api/history?limit=50`, and the house routes in section 4.8. All need the token in an `Authorization` header.

## 6. One turn, end to end

1. The microphone hears speech. VAD closes the utterance. Whisper transcribes it.
2. `wake.py` decides it is for Vision. `user.utterance` is published and the state becomes `thinking`.
3. `session.py` sends the text to the router, which streams it to Claude.
4. Fragments arrive as `vision.delta`. A sentence splitter hands each finished sentence to `tts.py`.
5. The first sentence plays. The state becomes `speaking`, `voice.level` drives the streaks in the Hall.
6. If Claude calls a tool, the gate decides. A free tool runs. An `ask` tool waits for you.
7. When the reply ends, `vision.reply` is published, the turn is written to the log, and the state returns to `idle` with the 20-second follow-up window open.

## 7. When things go wrong

| Failure | Behaviour |
|---|---|
| Claude rate limit, auth failure, timeout, offline | One retry, then the local model. Vision says it is running locally. |
| Credits exhausted or monthly cap reached | Talk moves to the local model and stays there. A notice says why and how to raise the cap. |
| No API key stored yet | Vision runs on the local model and a notice asks you to run `vision auth`. |
| Local model also unavailable | Spoken and shown error. The turn is logged as failed. |
| Speech recognition or voice fails to load | Text keeps working. A notice says voice is off and why. |
| Microphone permission missing | A notice with the exact setting to change. |
| Window loses the socket | Reconnects with back-off and reloads state from `/api/state`. |
| Daemon crashes | launchd restarts it. The session resumes from the log. |
| Gate request ignored | Denied after 60 seconds, logged as timeout. |
| A prop fails to load | The room still renders, with a plain stand-in, and a notice. |

## 8. Testing

- **Unit (pytest).** Bus, sentence splitter, wake matcher, echo guard, gate policy and timeout, router fallback with fake brains, memory store and search, config loading.
- **Protocol.** A test client connects to a daemon running the fake brain, sends `input.text`, and checks the event sequence and the log row. It also checks that a wrong token and a foreign `Origin` are refused.
- **Voice.** WAV in, WAV out, with the fake brain: the right utterance is detected, the reply is spoken, "stop" interrupts.
- **House.** Default plan loads; a personal file overrides it; a room with no position lands in the nearest free slot; overlapping, detached, unknown-agent and 21st-room requests are refused; removing a room that would strand another is refused; doors always connect every room to the Hall; a hand edit to the file raises the revision.
- **Web (vitest).** Store reducers, and wall and door geometry from a plan.
- **Live checks, done by the orchestrator.** Each "done when" item in section 2 is exercised for real: the daemon under launchd, the window in a browser with screenshots, a real Claude turn on the API credits with the measured time to first audio and its measured cost, a restart-and-recall, a gate yes and no, an offline turn, and a cap set low enough to trip.
- **Yours.** One pass at the real microphone, because nobody else can speak into it.

## 9. Stack

Python 3.12 with `uv`; FastAPI and uvicorn; the `anthropic` SDK; `keyring` for the Keychain; `sounddevice`; Silero VAD; Whisper on MLX; Kokoro; SQLite with FTS5; `pywebview`. Web: Vite, TypeScript, Three.js. Exact package versions are checked against current documentation when each part is built.

## 10. Layout

```
vision/            core/ brains/ voice/ memory/ gate/ house/
web/               src/scene/ src/hud/ src/net/
assets/            models/  textures/  design/
house/             default.toml, agent personas, library template (neutral, no personal data)
tests/
docs/superpowers/specs/
pyproject.toml
```

## 11. Risks, stated plainly

1. **Credits expire.** Each monthly grant runs out a month after it is issued and does not roll over. The grant issued on 2026-11-10 is good until 2026-12-13. Vision treats the credits as a monthly allowance and never assumes a balance carries forward.
2. **Runaway spend.** A loop that keeps calling the model could burn credits. The monthly cap, a per-reply output limit and the audit log bound this. With auto-reload off on the Console, the worst case is that the API stops answering and Vision falls back to the local model.
3. **Latency.** Calling the API directly removes the multi-second start-up that the Claude Code route showed in testing, but time to first audio is still unmeasured. One test call on 2026-11-12 with the talk model returned its first words in 0.9 seconds on a very small prompt; the real prompt is larger, and speech recognition and speech add to it. Three seconds is a target that the live check will measure.
4. **Subscription brains later.** Using Codex and Gemini through their subscription logins in slice 2 raises the same terms question this slice avoids for Claude. It gets checked then, before any code depends on it.
5. **Microphone under launchd.** macOS ties microphone permission to the program that asks. A background agent may need a one-time manual grant.
6. **Look.** A modelled house will start plainer than the painted concept on board 04. Lighting, textures and post-processing carry most of the look; furniture fills in room by room.
7. **Going public.** Three things must be settled before the repo is published. The cast: the repo ships original names (Vision as the assistant, then Brass, Wren, Tink, Tock and Rook), with no characters from any film or series. The project name: `OpenVision` was ruled out because it is already a known AI project and is taken on PyPI. The public name is OpenQuestAI, chosen on 2026-11-12, when it was free on PyPI, npm and GitHub; the assistant stays Vision and the command stays `vision`. The generated models and textures: each service's terms for the plan in use decide whether they can be redistributed, and that has to be checked before they are committed to a public repo.

## 12. How it gets built

The orchestrator fixes this spec's protocol and layout first, then hands independent parts to Opus and Sonnet subagents: core and protocol, brains and gate, the house, voice, the Mindspace, and memory. Asset generation stays with the orchestrator because it spends credits. The orchestrator reviews every part, runs the tests, and performs the live checks in section 8 before calling the slice done.
