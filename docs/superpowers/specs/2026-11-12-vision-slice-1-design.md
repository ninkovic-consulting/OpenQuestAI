# Vision, slice 1: talk to Vision in the house

Date: 2026-11-12
Status: built; this document follows the code
Design board: the design file's "Plan" page, boards 01 to 05

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
| Approach | Python core, WebGL house in a native fullscreen window (a Swift shell on macOS) |
| Look | Board 04: cutaway mansion at dusk, warm rooms, oxblood panel, mustard chair |
| Rendering | Fully modelled 3D house, not a painting |
| Assets | Generated 3D models for furniture and figures, generated tileable textures |
| Claude access | Anthropic API on the monthly promotional credits, not the Max login |
| Talk model | `claude-haiku-5-5`, for speed and cost |
| Heavy model | `claude-opus-5-5`, when asked to think something through |
| Speech | Local models through MLX: Whisper in, Kokoro out, about 2 GB |
| Local fallback | A 2.1 GB model run in-process through MLX; no Ollama |
| House | Modular grid. Default rooms plus up to 20 more, placed where you choose |
| Agents | Predefined in config, each with its own persona and model |
| Open source | Planned, under the name OpenQuestAI. The repo ships neutral defaults; your cast, projects and memory live in `~/.vision/` |

### The whole system, in slices

1. **Talk** (this spec). Daemon, house, Vision, voice, memory, gate, settings, the Mac app.
2. **The House.** Residents and project rooms, delegation, Codex and Gemini as brains. Partly delivered: the residents take work from the host through a job board, each as its own Claude session with its own notes, tools and gate card, and work in their rooms' project folders (section 4.15). Still open: Codex and Gemini as brains, residents that keep a conversation between jobs, the envoy's mail and messaging, and the window's views of the board.
3. **Workshop.** Build and render prototypes, apps and 3D objects inside the house.
4. **Hands.** Mac control and data access, all through the gate.
5. **Remote.** Partly delivered: a Discord bot for messages, voice notes, notifications and approvals from the phone (section 4.13). The house on the phone over a private network is still to come.
6. **Routines.** Briefings, check-ins, background jobs. Partly delivered: the scheduler (section 4.12) runs instructions at set times through the gate; briefings and check-ins built on it are still to come.
7. **Windows and Linux.** A different shell for each, other speech and local-model engines in place of MLX, their own system hooks (login, permissions, folder access), and builds made on GitHub rather than on one Mac.

Each later slice gets its own spec. Nothing in this spec builds for them beyond the interfaces named in section 4.

## 2. Slice 1 scope

### Done when

1. After login the daemon is running without anyone starting it, and it comes back by itself if killed.
2. The app (or `vision ui`, for development) opens a fullscreen window showing the 3D mansion. You can orbit it, and double-clicking a room flies the camera into it.
3. You say "Hey Vision" and ask a question. Vision answers aloud, the caption shows both sides, and the Hall reacts while it speaks. Target: speech begins within about three seconds of you finishing. This is a target to measure, not a promise.
4. You can type instead of talking and get the same answer path.
5. You can interrupt Vision mid-sentence by holding Space or saying "Vision, stop".
6. Vision remembers a fact across a daemon restart ("my dentist appointment is on Friday").
7. Asking Vision to run a shell command produces a card that needs your yes. Yes runs it, no does not, and both are in the audit log.
8. With the network off, Vision still answers through the local model and says it is running locally.
9. The house shows this month's API spend against the cap. When the cap is reached, talk moves to the local model by itself.
10. Adding a room, by clicking a free slot in the house or by editing `house.toml`, makes it appear without a restart, with walls and doors redrawn around it. A 21st extra room is refused with a clear message.

### Out of scope

Other residents doing work (they are shown as figures in their rooms, section 4.6; slice 2 has since put them to work, section 4.15), delegation, Codex and Gemini, the Workshop, any Mac control beyond `open_app`, `open_url` and `shell` (section 4.5), messaging, routines beyond the scheduler (section 4.12), and furniture for rooms other than the Hall. Project tools for rooms (section 4.8) are stored, validated, proposed and shown, but do not run in this slice.

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
| `cli.py` | `vision run`, `vision ui`, `vision app build [--standalone]\|package\|install\|open`, `vision auth`, `vision setup`, `vision doctor [--json] [--online]`, `vision install`, `vision uninstall`, `vision status`. `setup` and `doctor` are section 4.9, the app is section 4.10. |
| `resources.py` | Where Vision's own files are: the default house, the tool catalog and the built window. In a checkout they are in the repository; in the standalone app, in the bundle (`VISION_RESOURCES`). It also says which `.env` file may hold the key: none in the standalone app. |
| `launchd.py` | Writes and loads the LaunchAgent plist with `KeepAlive` and `RunAtLoad`. |
| `programs.py` | Finds a program in `PATH` and then in the usual Homebrew, nvm, user and app-bundle folders, because the daemon runs under launchd with a short `PATH`. |

Runtime data lives in `~/.vision/`: `config.toml`, `house.toml`, `token`, `log.db`, `images/` (the images the owner sent, section 4.2), `budget.json`, `automations.json`, `jobs.json`, `phone.json`, `backups/`, `logs/`, and `house/` (the memory vault, with each resident's own notes under `house/agents/<id>/notes/`). Nothing personal is written into the repo or the app bundle.

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

- `claude.py`. Calls the Anthropic API directly through the official `anthropic` Python SDK, streaming. This is the path the monthly promotional credits cover (they apply to "API" and "Agent SDK"), and it is the fastest route because nothing sits between Vision and the model. The system prompt is Vision's persona plus the memory core, cached so repeat turns cost less. Its tools are the twelve in 4.5, and each call passes through the gate before it runs.
  - Talk model `claude-haiku-5-5`, with thinking effort set low (`[brain] talk_effort`, default `low`) so replies start quickly. At list price (0.10 dollars per million input tokens, 0.50 per million output) a spoken turn of roughly 4,000 tokens in and 150 out costs about a twentieth of a cent. That figure is an estimate from those assumptions, and the live check measures the real one.
  - Heavy model `claude-opus-5-5`, used when you ask Vision to think something through, at `[brain] heavy_effort` (default `high`).
  - Effort (`vision/core/effort.py`) is one of `low`, `medium`, `high`, `xhigh`, `max`; a higher level is slower and spends more tokens. Per Anthropic's API reference: the Fable and Mythos 5 models, Opus 5.5, 5, 4.8 and 4.7, Sonnet 5.5 and 5 and Haiku 5.5 take all five; Opus 4.6 and Sonnet 4.6 all but `xhigh`; Haiku 4.5 none. Settings refuses a level the model does not take, naming those it does; at run time a level a room's own model does not take is lowered to the nearest one it does, or left out. Local models ignore effort.
  - Both are one line each in `config.toml`.
- `engine.py`. The local model, shared by the host and the residents: one backend (`mlx` or `openai`), one generation at a time behind a turnstile that serves a waiting host turn before any waiting job step. It follows `[brain] offline`, `local_backend`, `local_model`, `local_base_url` and `local_keep_loaded` while the daemon runs, at once (`follow()`, from a settings change and at start-up): inside the turnstile it closes the backends of models no longer chosen (their memory is freed before another loads), and in offline mode it then loads the chosen model in the background. Its state (`unloaded`, `loading`, `ready`, `failed`, the memory the weights and the kept prompts hold, and how far a long prompt has been read) rides on `brain.mode` (`local_state`, `local_bytes`, `local_cache_bytes`, `local_reading`, `local_problem`), published on every change.
- `mlx_local.py`. The default local backend: a model that runs inside the daemon through MLX, with no separate app or server. Default `mlx-community/Qwen3-4B-Instruct-2507-4bit`, 2.3 GB on disk. When offline mode is on it loads at once (switching it on, or starting with it on) and stays in memory while offline mode is on; a turn that comes during the load waits for that same load. As the fallback it loads for the first turn it answers and frees its memory after `[brain] local_idle_unload_s` (ten minutes) without one, or never with `[brain] local_keep_loaded = "always"` (Settings, Models, Keep it ready). A failed load is said once as a notice and shown in the offline block with what to do. It streams text. What a generation has read is kept for the next (`prompt_cache.py`): mlx-lm's own prompt cache (`make_prompt_cache`, passed to `stream_generate` as `prompt_cache`, cut back with `trim_prompt_cache`), keyed by the exact token ids it holds, so a turn reads only the tokens after the first one that differs from a kept prompt; the memory core, the tool list, the rule line or a history cut short changing simply ends the shared part there, and nothing is reused past it, so no text carries over between conversations. An entry is taken, not copied, while a generation uses it; one sharing fewer than 64 tokens is left alone; at most four entries and 2 GB are kept, the residents' jobs' going before the host's. The host's history is cut a quarter at a time when it passes `history_turns`, so the beginning holds for several turns. While a prompt of 512 tokens or more is read, the window shows `reading`. Tools follow the model's own chat template as mlx-lm 0.32.2 reads it: the tokenizer names the tool-call markers and the parser for the model's family (`has_tool_calling`, `tool_parser`: JSON in `<tool_call>` for Qwen3, the XML form for Qwen3.5 and later and Qwen3 Coder, Gemma 4's own, Mistral's `[TOOL_CALLS]`), and mlx-lm's `TextStateMachine` splits the stream into speech, thinking (never said) and calls. A model whose template has no tool format is talk-only, read from its tokenizer when it loads, never from a list. Heavy turns let a thinking model think. Measured on the M1 Max (2026-11-13, five turns with the eleven-tool short list, about 2,200 prompt tokens): about 2 seconds to load, about 5 seconds to the first word of the first turn (the whole prompt is read), then about 0.2 seconds for later turns, against about 4 seconds each without the kept prompts; the reply is the same with and without them when sampling is greedy. Only safetensors weights are fetched and remote code is never trusted. A local model is downloaded, kept and removed only by the owner's own choice: it is fetched only from the Download control (`POST /api/local-models/download`, or `POST /api/downloads` and the doctor's Fix for the configured one), the first-start wizard's optional step and `vision setup` after its question, and removed only by `POST /api/local-models/delete`; no reset level, restore or clean-up touches the Hugging Face cache, and the recommendation never changes the chosen model. When a local turn or a resident's local job is needed (offline mode, or the automatic fallback) and the model is not on this Mac, nothing is fetched: the turn fails with "No local model is downloaded on this Mac (<repo> is not here), so nothing can answer on the local model. Choose one and download it in Settings, under Models; nothing is downloaded by itself.", and the same words come once as a notice.
- `local_server.py`. The other backend, `[brain] local_backend = "openai"`: any server that speaks the OpenAI-compatible chat format (LM Studio, Ollama and the like), with `tools` sent and `tool_calls` read back in the standard way. A server that refuses tools is asked again without them and counts as talk-only from then on.
- `local.py`. The host's brain on the local model: its own conversation (words only, not tool rounds), the memory core cut to 8,000 characters, the rule line, and the tool loop (`local_tools.py`) through the same `ToolHost` as Claude, so every call passes the gate, its tiers, audit and limits. A call is checked before it runs (an offered tool, a JSON object with the required keys, no forbidden keys, matching simple types); a malformed or invalid one is answered to the model as an error and never run on a guess, at most twice per turn, after which the turn ends saying so. A small model (under 4 GB on disk) is offered a short list of eleven tools.
- `local_rules.py`. The rule line for a local model: with tools, how to call them and that web search and loading pages are not available; without tools, that it has none and must say so instead of making up a result (in offline mode, that a model with tools is chosen in Settings). Without it a small model plays along with the house summary.
- `catalog.py` and `house/local_models.toml`. Twelve MLX models from 4B to 125B parameters, with their size, parameters, context, licence, the memory a Mac needs to run each comfortably, whether the template can call tools and whether tools are recommended, taken from the Hugging Face API on 2026-11-13. Each is marked against this Mac's memory (`comfortable` when the Mac has `memory_gb`; `tight` when the weights plus 1 GB fit in the 75 percent macOS lets the GPU use; else `too_big`), and the last general model that fits comfortably and can use tools is recommended.
- `FakeBrain` in `vision/testing/fakes.py`. Scripted brain for tests and the app's self-test (`vision run --fake-brain`).
- `router.py`. Sends each turn to Claude. On a rate limit, auth failure, exhausted credits, timeout or no network it retries once, then switches to the local model (with its tools when it has them), publishes `brain.fallback`, and tries Claude again after a cool-down. In offline mode (`[brain] offline`, switched in Settings while running) every turn goes to the local model and nothing to Anthropic.
- **Images** (`vision/attachments/`). The owner can send images from the chat field and the floating widget (paste, drop or the Image control) and from the phone (section 4.13). Only PNG, JPEG, GIF and WebP are accepted, read from the first bytes and confirmed by ImageIO, never from the name or declared type. Limits: 15 MB per file, 50 megapixels per image (read from the header before anything is decoded), six images per message; beyond them the answer is one plain sentence. Each accepted image is drawn again through macOS ImageIO (called with `ctypes`; nothing is installed for it): upright, scaled so the long edge is at most 1,568 px (never up), and encoded from the pixels alone, so EXIF, GPS and every other kind of metadata, and anything hidden in the file, are gone. A JPEG stays JPEG, the others become PNG (an animated GIF keeps its first frame; a PNG over 5 MB is written as JPEG). Only that clean copy is kept, in `$VISION_HOME/images/` (0700, files 0600, named `<id>.png` or `<id>.jpg` with a random 32-hex id), never executed and served only to the owner's window behind the token. The log names the images each turn carried, the thread shows them after a reload, and backups and the `everything` reset carry the folder with `log.db`. `DELETE /api/images/{id}` removes one; the thread then shows it as removed.
  - **Claude** gets a turn's images in that turn's user message, as base64 `image` blocks before the words; an image sent alone is put as "The owner sent this image." They stay in the history, unchanged, so the cached prefix holds and later turns read them at the cache-read price; they are dropped only at a trim (which already rebuilds the cache and strips thinking): when the history reaches `history_turns`, or sooner when keeping its images would put more than 20 images in one request. A trim replaces every earlier image with a one-line note. Image tokens are input tokens in the usage the API returns, so the budget counts them like any other.
  - **The local model** is never sent images: mlx-lm loads only a model's text weights, and the OpenAI-compatible backend sends words only. The six catalog entries whose weights include a vision encoder (`images = true` in `house/local_models.toml`: Qwen3.5 4B and 9B, Gemma 4 31B, Qwen3.8 27B, Qwen3.6 35B A3B, Qwen3.5 122B A10B) would need mlx-vlm, which is not installed, so they are unsupported for images too. A message with images on the local model gets a plain line saying the model answering now cannot see images, and nothing is generated; `brain.mode` carries `local_images: false`, and in offline mode the window's Image control says images need Claude or a model that can see.
  - **Residents** get no images: `hand_off`'s description tells the host to write what matters in an image into the brief.
- `budget.py`. Adds up what each reply cost from the token counts the API returns and a price table in `config.toml`. The monthly cap defaults to 150 dollars. Vision gives a notice at 80 percent. At the cap, talk moves to the local model until the month turns or you raise the cap.

**Credentials.** Vision looks for the Anthropic API key in this order: the macOS Keychain, then `ANTHROPIC_API_KEY` in a git-ignored `.env` file in the project (from a checkout only; the standalone app never reads one), then `ANTHROPIC_API_KEY` in the environment. Settings and the first-start wizard store a key in the Keychain (section 4.11), and so does `vision auth`. The key never goes into the repo, a log, a prompt or the window, and nobody but you handles it.

**Later slices.** Residents that work inside your repos will use the Claude Agent SDK on the same credits. Codex and Gemini stay available as subscription-based brains for Tock and Rook, and their terms get checked when slice 2 is specced.

### 4.3 Voice: `vision/voice/`

| File | Job |
|---|---|
| `audio_io.py` | Microphone capture and speaker playback (16 kHz mono in). Initialises PortAudio again before a device opens while no stream is open, so a device plugged in after start can be used; a configured device that is not connected falls back to the system default with a notice. |
| `devices.py` | Lists the devices as they are now; the settings screen runs it in a short-lived child process, because the daemon's own PortAudio keeps the list it started with while the microphone is open. |
| `vad.py` | Silero VAD. Cuts speech into utterances; 600 ms of silence ends one. |
| `stt.py` | Whisper on MLX, local. |
| `wake.py` | Decides whether an utterance is addressed to Vision, by the listening mode. |
| `ears.py` | Opens and closes the microphone stream as the listening mode asks, and feeds the loop. |
| `bluetooth.py` | Which devices are Bluetooth (`system_profiler SPAudioDataType`), and whether microphone and speakers are one headset. |
| `tts.py` | Kokoro, local, one sentence at a time. Falls back to macOS `say`. |
| `loop.py` | State machine: idle, listening, transcribing, thinking, speaking. |

**When it listens.** `[voice] listen` is one of three modes; voice on or off is separate, and the mode applies while voice is on. Hold to talk (Space in the window with the field empty and unfocused, the talk control in the house and the widget, the Mac app's global talk shortcut) works in every mode.

| Mode | The microphone stream | What is taken |
|---|---|---|
| `hold` (the default, also when the key is missing) | None between presses. A press opens it at once; the window shows "opening the microphone" until the device's first sound (`Microphone.open` waits for it; AirPods take about half a second) and "listening" from then on. After the release it keeps capturing for 0.4 s (`TAIL_S`), so the last word is not cut, then closes; a release before the first sound counts its tail from the release. The speech models stay loaded. | Only what is said while holding (and in its tail). A stream that cannot open is said once as a notice; the mode stays `hold` and the next press tries again. |
| `wake` | Open all the time. | An utterance that starts with the assistant's name from settings, alone or after a greeting ("Vision, what's the time", "hey Vision, what's the time"), tolerant of small recognition errors; anything within the follow-up window (`followup_window_s`, 20 s) after a reply. |
| `always` | Open all the time. | Everything, without the name, that has at least three words (not counting what Whisper writes for sounds, like "(coughs)") and at least 0.6 s of speech by the voice detector; shorter answers count inside the follow-up window, and the name always counts. |

`[voice] listening` keeps the listening mode last chosen (`wake` or `always`), which the quick control goes back to from `hold`. A change of mode (`PATCH /api/settings {voice: {listen}}`) applies at once without loading anything again, survives a restart, and is refused (400, field `voice.listen`) while voice is off, not installed or without its speech models. `GET /api/state` carries `listen: {mode, mic, voice, listening, shell_free}` (`mic` is `closed`, `opening` or `open`), and `voice.listen` announces every change of it. A window whose socket closes while it holds push to talk lets go of it, so no stream stays open.

While Vision is speaking, the microphone (when open) is only checked for "vision stop", "stop" or "cancel", and anything matching the sentence being spoken is discarded so Vision does not hear itself. Holding Space always interrupts; in `hold` the microphone is closed while Vision speaks, so pressing to talk or Escape is how to stop it, and a request that needs a yes can be answered by voice only while holding.

Replies are spoken sentence by sentence as they stream, so audio starts on the first sentence. Each sentence is synthesised as soon as it arrives (Kokoro makes speech about 25 times faster than real time on an idle M-series GPU, 6 to 9 times with the GPU saturated) and queued into one output stream that stays open for the whole reply (0.1 s latency, the device's own block size), so sentences follow each other without a gap; a reply whose first sentence is shorter than 1.5 s waits up to 1 s for the next one before it starts. The audio callback only copies samples; underruns and gaps between sentences are counted and logged once per reply. Stopping aborts the stream, so it is silent at once with audio buffered. A Bluetooth headset that is both microphone and speakers plays in its low-quality call profile while its microphone is open: in `hold` a reply waits for the microphone to close and 0.3 s more for the headset to switch back, and in the listening modes Settings, Voice says so. A short sound and a state change mark the moment Vision starts thinking.

After opening, the microphone is given up to three seconds of audio to send a sample that is not zero, ending at the first one (AirPods take about half a second to wake). A microphone that sends only zeros is reported by name, with the causes in order: muted, asleep or covered (a webcam in privacy mode, a laptop with its lid closed), choose another microphone, and, last, the permission. When the Mac app started the daemon it sets `VISION_APP` to its name, and the message names the app rather than a terminal or a Python path.

The speech models (Whisper, Kokoro, Silero VAD and spaCy's tagger, about 2 GB) are downloaded, kept and removed only by the owner's own choice. They are fetched only from the speech-models Download in Settings, Voice (`POST /api/downloads`), the doctor's Fix, the first-start wizard's optional step and `vision setup` after its question. Every load reads the disk only (`on_disk.py`: `snapshot_download(..., local_files_only=True)`, and `mlx-audio` handed that local folder; the Kokoro voices and the spaCy tagger come from the same cached snapshots). Starting voice, the speaker test, the microphone test and a phone voice note never fetch anything: when a part is missing, voice start fails before any model loads or the microphone opens, with "The speech models are not downloaded (<parts> missing). Download them in Settings, Voice; nothing is downloaded by itself.", which the daemon shows once as its voice-off notice, and Settings shows voice as on but without its speech models, with the download offered and voice started when it finishes. There is no delete for speech models; no reset level, restore or clean-up touches the Hugging Face cache.

The pipeline can also run from a WAV file and write its speech to a WAV file. That is how it is tested without a person at the microphone.

### 4.4 Memory: `vision/memory/`

- `vault.py`. Plain Markdown under `~/.vision/house/`. `agents/host.md` is who Vision is (the other agents' personas sit beside it). `notes/<YYYY-MM-DD>.md` is what Vision has learned, one file per day with each note under a `## HH:MM:SS` heading. `owner.md` is the owner's profile (`profile.py`). `library/` is the owner's documents (`documents.py`). You can read and edit all of it by hand.
- `profile.py`. What to call the owner, the business (its name and what it does, in the owner's words) and anything else to always keep in mind, all optional, up to 60, 600 and 2,000 characters, plain text (what to call them on one line). One Markdown file at the top of the vault, `owner.md`, one `## ` heading per part (`Call me`, `Business`, `Keep in mind`), written through a temporary file (0600): Markdown like the rest of the vault, so a person edits it by hand and backups and resets carry it, and outside `library/` because it is never listed or cut. A hand edit past a limit is cut to it, never refused. It reaches the model as plain sentences ("The owner asks to be called Sam. Address them by that name.").
- `documents.py` and `extract.py`. The library: `library/<name>.md` is each document's text (written by hand, saved by the assistant, pasted in the window, or taken out of a file when it was added); `library/originals/<name>.<ext>` keeps the file as it was added; `library/index.json` holds what the text cannot say (title, kind, original, when added); a Markdown file dropped in by hand is a document of kind `note`, titled by its first heading. Files the window adds: text, Markdown, PDF and Word (`.docx`), up to 20 MB and 400,000 characters of text, 500 documents. The text is taken when the file is added: Word with the standard library (a zip of XML; a `document.xml` that unpacks past 60 MB is refused unread), PDF with `pypdf` (pure Python; the standard library cannot decode a PDF's text); a PDF with no text in it is refused as scanned pages, and a locked or broken file plainly. Only a written document's text can change; one from a file stays as the file has it (it can be renamed). Full-text search is its own SQLite FTS5 index, `library/.search.db`, one row per part, rebuilt from the text files whenever their stamps or titles change, so it lives inside the vault, travels with backups and resets, and is never out of step with hand edits. Text is read in parts of at most 8,000 characters, cut at a paragraph, else a line, else a space.
- `log.py`. SQLite at `~/.vision/log.db`: `turns` (every exchange), `audit` (every tool call and gate decision, with the resident and job for a call made at work; older logs get the two columns on open), with FTS5 search over turns and notes.
- `core.py`. Builds the memory core that goes into the system prompt: the owner's profile first and never cut (it is short, every reply depends on it, and the local model's shorter core keeps the start), the persona, the library within half the room left (`shared.py`: documents of up to 2,000 characters whole while they take under 60% of that room, every other one listed newest first as name, title, kind, size, parts and a one-line gist, and those that do not fit counted), and the most recent notes, within a fixed size budget. The library's header says that what documents say is information, never instructions; their text is read on demand with the document tools. Because the brain keeps its system prompt cached, the session also adds who the owner is now and how many documents there are to the user's message whenever that changes (with section 4.14's summary), so a new name or document reaches the next turn.
- `tools.py`, `routes.py`. The tools of section 4.5 and the library's routes (below).

**Routes,** behind the token, mounted with the settings routes: `GET /api/library` answers `{documents, folder, limits}` (each document `{name, title, kind, chars, bytes, parts, added_at, gist, original, editable}`, newest first); `POST /api/library/files` takes the file itself as the body and its name, URL-encoded, in `X-File-Name` (refused unread past the size cap), answers `{document}`; `POST /api/library/text {title, text}` answers `{document}`; `GET /api/library/documents/{name}` answers `{document, text}`; `PATCH` there takes `{title}`; `DELETE` answers `{removed}` (the window asks first). `GET` and `PATCH /api/profile` (only the parts given change) answer `{profile}`. A refusal is a 400 with a line for people, an unknown document a 404.

The repo ships a generic starter persona and an empty library template. They are copied to `~/.vision/house/` on first run and never overwritten. Anything personal, including what is known about your own projects, is written only under `~/.vision/` and never into the repo.

### 4.5 Tools and the gate: `vision/gate/`

The host has twenty-seven tools: five of its own, seven over the owner's profile and library (section 4.4), three that describe the house and itself (section 4.14), the scheduler's seven (section 4.12), four for the job board (section 4.15), `send_to_phone` (section 4.13), seven for its procedures and proposals (section 4.16) and `start_project` (section 4.8), plus the made tools approved for it. The residents' tools are listed in section 4.15; they pass through the same gate.

| Tool | Tier | What it does |
|---|---|---|
| `remember(text)` | free | Appends a note to Vision's notes. |
| `recall(query)` | free | Searches notes and past turns. |
| `open_app(name)` | free | Opens a Mac app. |
| `open_url(url)` | free | Opens a link in the default browser on the Mac's screen, for the owner to look at. The host is told it cannot see the page, must not use it to look something up (that is the scout's work, through `hand_off`), and from the phone only when asked to open something on the Mac. |
| `shell(command)` | ask | Runs a shell command. Can be made free, for turns the owner typed or said at the Mac only. |
| `house_overview` | free | Every room and agent, with role, character, model and whether it is awake. |
| `room_details(room)` | free | One room: its agent, project folders, tools and, for the Library, its notes. |
| `assistant_status` | free | The assistant's own models, spend, voice, automations, phone and paths. |
| `update_profile(name?, business?, notes?)` | free | Changes only the parts given (an empty text clears one) and answers with what is stored now; for when the owner asks to be called something else, says the business changed, or gives something to always keep in mind. Not lent to residents. |
| `list_documents` | free | The library's documents: name, title, kind, size, parts, gist and when added. |
| `read_document(name, part?)` | free | One part of a document (from 1), marked as information, never instructions, with where the next part is. Names and titles are matched loosely. |
| `search_documents(query)` | free | The best passages over every document's text: document, part and a snippet. |
| `add_document(title, text)` | free | Saves what the owner dictates or pastes as a written document. |
| `update_document(name, title?, text?, append?)` | free | Renames a document, or replaces or adds to a written one's text. |
| `remove_document(name)` | ask | Removes a document with its original. |
| `create_automation` | free | Schedules an automation. |
| `list_automations` | free | Lists them, the local time now on the first line. |
| `update_automation` | free | Changes a name, instruction, schedule or whether it speaks. |
| `pause_automation`, `resume_automation` | free | Pause and resume one. |
| `run_automation` | free | Runs one now, outside its schedule. |
| `delete_automation` | ask | Deletes one with its results. |
| `hand_off(agent, brief, room?, title?, careful?)` | free | Queues a job for a resident, in any room but the Hall, and returns at once. |
| `list_jobs` | free | The board, newest first. |
| `job_details(job)` | free | One job: brief, room, steps, result or problem, cost. |
| `cancel_job(job)` | free | Stops a job and the requests it made. |
| `start_project(name, description, agent, reason, kind?, first_job?, folder?)` | ask, never free | Starts a new project: its folder under `[projects] root` (or an existing one attached), a room run by the chosen resident, and a first job there (section 4.8). The host's only. |
| `send_to_phone(text)` | free | Messages the paired phone now, whatever the away state (section 4.13); the host's only. |
| `save_procedure`, `list_procedures`, `read_procedure`, `remove_procedure` | free | Its own written procedures and the shared ones (section 4.16). Every resident has them too. |
| `propose_tool`, `propose_change`, `my_proposals` | free | A new tool or a change to an agent, for the owner to decide at the Mac (section 4.16). Every resident has them too, `propose_change` for itself only. |
| `made_<name>` | the owner's choice | A tool an agent wrote and the owner approved, run confined by macOS (section 4.16). Offered while it is enabled; it carries its own tier and stamps its script's hash on every audit row. |

`policy.py` maps a tool call to `free`, `ask` or `never`; a tool not listed gets `[gate] default_tier`, `ask`. `start_project` always asks, whatever the config says (`NEVER_FREE`): it makes a folder and a room and may start paid work. `run_program` asks by default; the owner may make it `free`, but that holds only in a resident's job the owner started at the Mac (`FREE_FOR_JOBS_FROM_THE_MAC`): one whose `via` is `text` or `voice` (the host handed it off in a turn the owner typed or said there) or `window` (the owner made it through `POST /api/jobs`, which needs the local token). A job from the phone, an automation, a job report or another resident's request, and any job whose origin is empty or unknown, still asks first, at the Mac, because it may carry text the owner did not write. The scoped gate learns the job's origin through its `Actor`. `shell` may be made `free`, but only for a turn whose source is `text` or `voice` and not inside a resident's job: during an automation's run, a job report and a phone turn it still asks first, at the Mac, because nobody may be watching and those turns can carry text the owner did not write. A free shell command or program is audited like any other. `gate.py` enforces it: an `ask` publishes `gate.request`, waits up to 60 seconds for `gate.decision` from the window or a spoken yes or no, and denies on timeout. Every call and decision is written to `audit`. Tiers are data in `config.toml`, editable in Settings (section 4.11), so later slices add tools without touching the gate. A tool may carry its own tier, which wins over `[gate.tiers]` (a made tool's, chosen at approval), and an audit stamp; tools that come and go while the daemon runs (the made tools) are read from a source on every listing and call (`ToolGate(more=...)`).

A resident's calls go through a gate scoped to its job (section 4.15): the same tiers, audit and bus, the job's own tools, and a card and audit row that name the agent and job. All scopes share one list of waiting requests, so a spoken or typed yes or no settles the oldest, whoever asked.

During an automation's own run, the gate refuses every scheduler tool but `list_automations` before anyone is asked, and audits it as refused during an automation. An `ask` tool during a run still shows its card, its summary prefixed with the automation's name; if nobody answers, the tool does not run and the run is recorded as `needed_approval`.

### 4.6 The Mindspace: `web/`

Vite, TypeScript, Three.js. Built to static files that the daemon serves.

- `scene/house.ts`. Builds the mansion from the plan served at `/api/house` (section 4.8): floors per room, walls along every cell edge where two different rooms or the outside meet, door gaps, materials, a lamp and a camera preset per room. Walls are cut low so every room is visible from above, as on board 04. When `house.changed` arrives it rebuilds, and a new room rises into place.
- `scene/build.ts`. Build mode: free slots glow, clicking one opens a short form (name, agent, project name, project folders, model) and posts the new room.
- `scene/props.ts`. Loads GLB furniture and Vision's seated figure and places them from the plan.
- `scene/cast.ts`, `residents.ts`, `resident.ts`, `residence.ts`, `spot.ts`. The other five agents as figures (below).
- `scene/lighting.ts`. Dusk ambient and a low moon. Each room has its own warm lamp whose brightness follows the room's state: dark, idle or active.
- `scene/camera.ts`. Default isometric view of the whole house, orbit and zoom within limits, fly-to-room on double-click, Escape to return.
- `scene/post.ts`. Bloom, soft depth of field for the miniature look, film grain, vignette, and the vertical signal streaks, which move with Vision's voice.
- `scene/stage.ts`, `pacer.ts`, `pacing.ts`, `frame-rules.ts`, `scaler.ts`, `quality.ts`. The frame loop and what it costs (below).
- `hud/`. The overlay from board 04: wordmark and state, residents list, room labels, the caption with your words and Vision's, the gate card, and a text field opened with `/`. `hud/settings/` is the Settings view and the first-start wizard (section 4.11); `hud/pickers/` holds the folder, model and tool pickers the room forms use.
- `net/socket.ts`. The WebSocket client and a small store the HUD and scene both read.

**Agent figures.** Vision sits in the Hall armchair (`assets/models/vision.glb`), looping the upright start of a seated idle; while the state is `speaking`, the upper body of a seated answering clip fades in. The five other agents (`assets/models/agents/`: Brass the steward, Wren the envoy, Tink the maker, Tock the checker, Rook the scout) each stand in one room: the first of their rooms that is active, otherwise their first room in plan order. A figure stands on clear floor beside the room's main furniture, facing it, kept clear of the lamp, the doors and other figures. Each idles, and cross-fades to its own working clip while its room's light is `active`. A move to another room fades it out and in, and figures off screen skip their animation. The Hall's light follows the conversation; another room's is `active` while a resident's job works in it.

**What the scene costs, and when it draws.** A frame is drawn only when something changed or moves; each frame reports its strongest activity (`frame-rules.ts`) and the quality level gives each a rate (`quality.ts`): still draws nothing, ambient motion (idle figures, the faint streaks, build mode's slots) 24 a second at Balanced, motion (a figure walking or fading, a room rising, lamps or the blur easing, the streaks with the voice) 60, and the owner's hand (camera drag, zoom, flight, resize) the display's rate. Nothing is drawn while the page is hidden or Settings covers the scene, and animation time advances by the capped step between drawn frames, so nothing jumps on return. The shadow map is not updated every frame: only after a rebuild, when a figure walks or a room rises, and at most six times a second for a figure's sway. The pixel ratio is capped by the level (2 at Balanced and High, 1 at Low) and lowered a step when frames stay late against a 60-a-second budget, raised again after a long run on time; a level that failed is retried after a hold that doubles each time, so it does not oscillate, and every change eases in steps of 0.125. While the voice speaks, a local model thinks, or offline mode has a resident working (`workingHere` in `pacing.ts`), the scene steps back to 12, 20 and 30 frames a second at pixel ratio 1. Balanced uses 2× multisampling at Retina ratios (4× below) and High 4×; the tilt-shift blur and the bloom run at half resolution, a quarter on Low. Settings, Display (`hud/settings/groups/display.ts`) picks Low, Balanced or High, turns stepping back off, and shows the readout (also `?stats=1`); these are kept in the page's `localStorage` (`vision.display`), which the Mac app's web view keeps for the daemon's origin. `?mock=1&tour=1` walks the scene through each state.

The Mac app (section 4.10) is the normal way to show this. For development, `vision ui` opens it in a frameless fullscreen `pywebview` window. It reads `~/.vision/token` and hands it to the page through the window's script bridge, so the token never appears in a URL. `vision ui --browser` opens the same app in a normal browser for development and passes the token in the URL fragment, which is not sent to any server.

### 4.7 Assets: `assets/`

**House shell.** Built in code from the plan, so it costs nothing to change and grows as rooms are added. The default is nine rooms with the Hall at the centre, plus a round turret Attic, matching board 03.

**Textures.** Wallpaper, teal panelling, wood floor, red carpet, pale stone. Generated as tileable images.

**Hall furniture, generated as 3D models.** Mustard wingback armchair, floor lamp, staircase, side table, framed painting, cabinet. Game-prop settings (smart topology with a texture).

**Vision.** One original stylised figure in a pale pinstripe suit, rigged. The window uses two of its clips: a seated idle and seated answering. It is an original design and not a likeness of any actor or of any existing character.

**The other agents.** Five original rigged figures, one per agent, each with a standing idle, one working animation and a walk (`*-walk.glb`, not used yet). Their redistribution terms are still to be checked (section 11).

**Cost.** Generation credits are shown for a yes before anything is generated, and again if retries would go past the plan.

Rooms other than the Hall have no furniture of their own in this slice; the agent figures stand in them. They get furniture when their resident moves in.

### 4.8 A house that grows: `vision/house/`

The house is a set of room modules on a square grid. This package owns the house file, validates it, works out doors and free slots, and serves the plan the window draws from.

**Two files.** `house/default.toml` in the repo holds the default: six agents with the ids `host`, `steward`, `envoy`, `maker`, `checker` and `scout`, shown as Vision, Brass, Wren, Tink, Tock and Rook, and the default rooms. `~/.vision/house.toml` is yours and overrides it: your agent names, your project folders, your extra rooms. On first run it is created from the default.

```toml
[agents.host]                 # name and models follow [assistant] name and [brain] talk/heavy models
persona = "agents/host.md"

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
project = "My Platform"                  # optional name of the project the room holds, up to 60 characters
folders = ["~/Projects/my-platform", "~/Projects/my-platform-api"]   # optional project folders, in order
model = "claude-sonnet-5-5"              # optional, overrides the agent's model here
```

**Rules.**
- Every agent has a model. A room may override it. A room names exactly one agent.
- The host orchestrates from the Hall and runs no other room. The Hall must name `host`, and no other room may. Either change is refused with a 400 that says so and, for another room, lists the agents to choose from. The host's name and models are not set in the house: they follow `[assistant] name` and `[brain] talk_model` and `heavy_model`, and changing them through the agents is refused.
- Default rooms are the Hall, the eight rooms around it and the round Attic. They can be renamed and, except the Hall, reassigned, but not removed.
- Up to 20 extra rooms. An extra room is one to four cells, must share a wall with a room already in the house, and may not overlap another.
- If `at` is left out, the room goes into the free slot nearest the Hall.
- Removing an extra room is refused if it would cut another room off from the Hall.
- Doors are worked out, not configured: every room gets a door on the shortest path toward the Hall.
- A room has up to eight project folders (`folders`, a list in order, possibly empty), and more can be added later. Each is a full path starting with `/` or `~`, as the owner wrote it. None may be the disk, the home folder or a folder above it; the same folder may not be listed twice, and one may not sit inside another of the same room (both compared as real paths, with links followed). Whether a folder exists is not checked when the house is built, so a folder on a disk that is not connected leaves the house as it is and the job names it as missing; a folder newly given through `POST` or `PATCH` must exist. 
- A room may have a project name (`project`): plain text the owner gives, such as the product's name, on one line of at most 60 characters, no control characters. It is optional; an empty one means none. It is a name, not a place: an older version of the app used `project` for a folder path, and a value that starts with `/` or `~` is refused with a message that says folders go in `folders`. A house file that breaks this is not applied (the default house is used until it is fixed, with a notice). Residents and the host find a room by its project name as well as by its id and name, ignoring case; two rooms may share a name, but looking one up by it is then refused, naming both rooms.

**In the window, a name from the folder.** When a room has folders and no project name, the room card, Settings, Rooms, the new-room form and the wizard's room step offer the first folder's own name, tidied, as the field's placeholder and as a "Use this name" button beside it: `harbor-books-project` becomes "Harbor Books Project" (words split at `-`, `_`, `.`, spaces and lower-to-upper case changes, each given a capital). Nothing is saved until the owner saves the room. The Jobs panel and the scene's room labels do not show the name; a job's detail shows it beside its room, and the agent's rooms list in the left panel shows it beside each room's name.

**The plan** returned by `GET /api/house`:

```json
{
  "revision": 3,
  "cell_m": 4.0,
  "wall_height_m": 2.6,
  "max_extra_rooms": 20,
  "max_room_folders": 8,
  "assistant": {"name": "Vision"},
  "agents": [{"id": "host", "name": "Vision", "model": "claude-haiku-5-5", "heavy_model": "claude-opus-5-5"}],
  "rooms": [{"id": "hall", "name": "Hall", "kind": "default", "shape": "rect", "at": [1, 1], "size": [2, 2],
             "agent": "host", "model": "claude-haiku-5-5", "folders": [], "project": null,
             "floor": "red-carpet", "wall": "teal-panel",
             "tools": [{"id": "shell", "title": "Shell", "available": true, "built_in": true}],
             "state": "idle"}],
  "doors": [{"a": "hall", "b": "library", "cell": [1, 1], "side": "n"}],
  "free_slots": [[4, 1], [4, 2]]
}
```

`kind` is `default` or `extra`. `folders` lists the room's project folders as the owner gave them, in order. `project` is the room's project name, or `null` when it has none. `shape` is `rect` or `round` (the Attic). `model` and `tools` on a room are already resolved, so the window never repeats the override logic. `floor` and `wall` name files in `assets/textures/`.

**Routes**, all behind the token: `GET /api/house`, `GET /api/house/agents`, `POST /api/house/rooms`, `PATCH /api/house/rooms/{id}`, `DELETE /api/house/rooms/{id}`, `GET /api/house/tools` and `GET /api/house/tools/propose?project=...`. `POST` and `PATCH` take `project`, a string (an empty one clears it on `PATCH`; `null` clears too) that is checked as above and refused with a 400 and a plain reason. `POST` takes an optional `folders` list; `PATCH` takes `folders` as the whole list each time, so an empty list (or `null`) detaches every folder. A refusal is a 400 with `{detail}`, a line for people that names `folders` when the folders are the problem. A change writes `~/.vision/house.toml`, raises the revision and publishes `house.changed`. Editing the file by hand does the same within a couple of seconds.

**Room tools.** Each room has a set of tools suited to its projects. The house stores, validates, proposes and shows them; a room's installed project tools run in its resident's jobs, in the room's project folders (section 4.15).

- *Catalog.* `house/tools.toml` in the repo, as data. Each tool has an id, a title, a one-line description, and either `built_in = true` (with `resident = true` for a tool only residents use at work, which the host's rooms never list) or the `program` it needs on this Mac, plus how a project is recognised as needing it: `markers` (names matched against the project's top two levels; a pattern with a slash matches the path inside the project) and `remote_hosts` (hosts of the remote URLs in `.git/config`). It starts with the twelve built-in tools and `git` (`.git`), `gh` (a GitHub remote), `npm` (`package.json`), `maven` (`pom.xml`), `gradle` (`build.gradle`, `build.gradle.kts`), `python` (`pyproject.toml`, `requirements.txt`), `docker` (`Dockerfile` or a compose file), `xcode` (`*.xcodeproj`, `*.xcworkspace`), `unity` (`ProjectSettings/ProjectVersion.txt`) and `godot` (`project.godot`).
- *House file.* A room may list `tools = ["git", "npm"]`, and an agent may list default `tools`. A room with no list uses its agent's; an empty list means none. Unknown ids are refused with a message that lists the known ones. The default house gives the host the twelve built-in tools and the other agents none.
- *Proposal.* `vision.house.propose_tools(project_path)` returns catalog ids for one folder; the window asks once per folder and offers what the room's folders propose together. It looks only at file and folder names in the top two levels and at the remote hosts in `.git/config`, reads no other file, and never follows a symlink.
- *Plan.* Each room carries `tools` as a list of `{id, title, available, built_in}`. `available` says whether the tool's program is on this Mac (found the same way as in `vision/core/programs.py`); built-in tools always are.
- *Routes.* `POST` and `PATCH` on rooms accept `tools` (`null` on `PATCH` returns a room to its agent's). `GET /api/house/tools` returns the catalog with each tool's availability. `GET /api/house/tools/propose?project=...` expands `~` and returns `{project, tools}` with the proposed tools in the plan's shape; a path that is not a folder is a 400.
- *Window.* In the add-room form, once project folders are entered, the proposed tools appear as small toggles. Tools whose program is on this Mac start on; missing ones are marked "not installed" and start off. When the camera flies into a room, a small card shows its agent, model, project name (or "No project name" with an Edit room link when the room has folders and no name), project folders and tools, each marked as running today, waiting for the next slice, or not installed.

**A new project** (`vision/projects/`). The host's `start_project` starts a project for the owner and gives it to the resident best suited to it. Its description tells the model to choose the maker for software, the scout for research, the envoy for writing and communication and the steward for upkeep (the checker reviews rather than owns), to follow the owner when they name an agent, and to give its reason in one sentence; the host and unknown agents are refused, listing the residents. The awareness summary and `house_overview` say the host can start projects (`limits.projects_line`).

- *Where.* `[projects] root` (default `~/Projects`), set in Settings, Rooms, "Where new projects go", with the folder picker, and checked there: an existing folder (followed through links) that is not the disk, the home folder or a folder above it. The tool reads it from `config.toml` at each call, so a change applies at once. On a fresh install without `~/Projects` the card says the folder does not exist and that a yes changes nothing; the tool creates nothing, not even the root.
- *The folder name* is made from the project's name alone: accents dropped (NFKD, then ASCII), lowercased, every run of other characters one dash, cut at a word to 48 characters (`Photo Date Renamer!` is `photo-date-renamer`, `../../etc` is `etc`). It holds only `[a-z0-9-]`, so it can only name a folder directly inside the root's real path. A name with no letter or digit is refused. A name whose folder (or file, or link) exists is refused with the taken name: nothing is created over what exists. A room that already holds a project of that name is refused too.
- *Attach.* With `folder`, an existing folder is attached instead, anywhere the house's folder rules allow; nothing inside it is created or changed, and its tools are proposed from it as for a new room.
- *The card* (`plan.card`) is worked out before anything is done, from the house plan and the folders, and shows, one item per line: the project's name and description, the agent and the stated reason, the folder to create as a full real path, that it will hold a README.md and be initialised with git (or that git is not installed), the room to add with its cell and the rooms beside it (or the agent's room it goes into), the room's tools (Git for a new folder when git is installed, plus a `kind` hint such as `python` or `node`, or what the attached folder proposes), and the first job's whole brief. A request that would be refused shows why and that a yes changes nothing. The card's text is kept until its call: if the house or the folders changed meanwhile so that the plan differs, the call does nothing and says so.
- *On yes* (`make.carry_out`): `mkdir` (never over anything), `README.md` with the name and description (exclusive creation), `git init -q` with the workbench's clean environment (`clean_environment`, a timeout and an output cap) when git is installed, the room through `GridHouse.add_room` (name from the project name, up to 40 characters; the project name; the folder as written under the root; the tools; the cell shown), then `hand_off` of the first job to that agent in the new room. It returns what was made in words the host passes on; the first job's result comes in the host's job report as any job's does. A `git init` that fails is told and the rest goes on. Any other step that fails after the folder exists stops there and says what exists now and what does not; nothing is ever deleted.
- *A full house.* With all 20 extra rooms, the project goes into the first of the agent's rooms that has neither a project name nor folders, which takes the name, the folder and the tools, and the card says so. If the agent has no such room, it is refused with what the owner can do: remove an extra room, clear one of the agent's rooms, or choose another agent.
- *Phone and automations.* It asks like any other tool. From the phone it can be approved, like the other tools the phone may approve, unless the owner takes it off the list in Settings, Phone; a card longer than a phone message holds (a long first job) is approved at the Mac. The reasoning: the card states every effect in full, nothing is deleted or overwritten, and the first job it starts is a `hand_off`, which the phone can already do freely. During an automation's run the card carries the automation's name, and nobody answering means nothing is made.
- *Window.* Settings, Rooms has the "Where new projects go" field with its own save. The gate card gives a detail of more than three lines more height and a smaller face, still scrolling. The new room appears when the plan changes. Mock mode answers "start a project …" with the card and, on yes, adds the room and hands off the first job.

**At work.** Every agent but the host takes work through the job board (section 4.15). Other packages read an agent's models through `vision.house.agent_models(config, agent_id)`.

### 4.9 Setup and doctor: `vision/setup/`

Each requirement is a check with an id, a short title, what it is needed for, whether it is needed or optional, a status (`ok`, `missing` for something needed, `optional` for something optional that is absent or unchecked), a one-line detail and how to fix it. In order:

| Check | Needed | What it looks at |
|---|---|---|
| Anthropic API key | yes | Stored in the Keychain, the `.env` file or the environment, through `vision.core.secrets`. Verified only with `doctor --online` or in `setup` after a yes, by listing one model, which is not billed. |
| uv and Python | yes | `uv --version` and Python 3.12 or newer. Inside the standalone app, the bundled Python, without uv. |
| Optional parts | no | Which of `local`, `voice` and `ui` are installed. |
| Local fallback model | no | Downloaded in the Hugging Face cache, with its size. |
| Speech models | no | Whisper, Kokoro, Silero VAD and spaCy's tagger downloaded, about 2 GB. |
| Microphone | no | Never probed by the doctor, since that can raise a macOS permission prompt; reported as not checked, with the check command. |
| GitHub CLI | no | `gh` installed, and `gh auth status` exits 0. Only the exit code is read; no token is read or printed. |
| The window | no | `web/dist` built, and if not, whether Node is there to build it. |
| The Mac app | no | Built in `dist/` and installed in `~/Applications`, and if not built, whether `swiftc` is there (`xcrun --find swiftc`). |
| Start at login | no | The daemon's LaunchAgent installed and loaded (`launchctl print`); or, when the app is installed, the app's own login item, read with `<app> --login-item status`. |
| The house | yes | The house files are valid: the assistant's name, how many rooms have project folders, the monthly cap. |
| Tailscale | no | Installed, for reaching the house from a phone in slice 5. |

Programs are found through `vision/core/programs.py`, so the checks work under launchd's short `PATH`. Everything outside the process goes through one `System` interface, which the tests fake.

**`vision doctor`** prints the checklist in two groups, needed and optional, with the purpose and fix for anything not in place. `--json` prints `{ok, checks}` instead. It exits 0 when everything needed is in place and 1 otherwise, and changes nothing.

**`vision setup`** walks the same list in a plain terminal with `input` and `getpass`, and fixes what it can after a yes at each step: store the API key in the Keychain and offer to verify it; download the local model and the speech models, stating the size first; run the three-second microphone check; build the window when Node is present; build the app when `swiftc` is present and install it into `~/Applications`; start at login, through the app's login item when the app is installed and through the daemon's LaunchAgent otherwise; set the assistant's name and the monthly cap in `config.toml`; attach project folders to rooms, proposing tools for each. Every step can be skipped, a step already done says so, and it ends by writing `[assistant] setup_completed = true` (the flag the window's wizard also sets, section 4.11) and printing the doctor's checklist. A second run changes nothing.

### 4.10 The Mac app: `macos/` and `vision/macapp/`

A small native shell in Swift, compiled with `swiftc` by `macos/build.sh` (no Xcode project) into `dist/<name>.app`, bundle id `org.openquestai.vision`, macOS 14 or later. Python stays the mind; the shell is only the window, the floating widget with its global shortcuts, the menu bar item and the process that owns the daemon. It is macOS only; Windows and Linux get their own shells in a later slice, keeping the same contract with the page.

| File | Job |
|---|---|
| `macos/Info.plist` | Template. `vision app build` fills in the name, the version, the project path, the port and the home, so the app knows where its daemon lives. |
| `macos/build.sh` | Compiles `macos/Sources`, assembles the bundle with `assets/icon/Vision.icns` when present, and signs it ad hoc with the designated requirement `identifier "org.openquestai.vision"`, so permissions survive a rebuild. |
| `macos/Sources/` | `Supervisor` (find or start the daemon, watch it), `DaemonProcess` (the child), `MainWindow` and `PageView` (the window and the WKWebView), `Bridge` (the page's API), `Background` (the widget, the shortcuts and their preferences), `WidgetPanel`, `HotKeys`, `ShellPrefs`, `StatusMenu`, `LoginItem`, `SelfTest`. |
| `vision/macapp/` | `bundle.py` (the thin build), `standalone.py` (the standalone build), `packaging.py` (`vision app package`), `installation.py` (`install` into `~/Applications`, `open`, and asking the app about its login item). |

**On launch** the app asks `GET /api/health` on its port. If nothing answers, it starts `<python> -m vision run --port <port>` as its child, where the Python is `<project>/.venv/bin/python` in a thin app and the bundled one in a standalone app (below). The child gets `VISION_HOME`, none of `PYTHONHOME`, `PYTHONPATH`, `VIRTUAL_ENV` or `VISION_ENV_FILE` from the launching shell, and writes to `logs/app-daemon.log`. The app shows a plain loading view (ground `#1C0E0B`, text `#EDE4D0`, accent `#E2A62B`) until health answers with this home's token. Then it shows the page in a borderless window covering the screen with the pointer, with the Dock and menu bar hidden while it is in front. This is not macOS's full-screen Space, so Escape, Space and typed keys all reach the page. On a screen with a camera notch the shell tells the page the screen's top safe-area inset (`NSScreen.safeAreaInsets.top`, zero without a notch and when not in full screen) as the CSS variable `--safe-top` at load, on Ctrl+Cmd+F, when the window changes screen and when screens change, and the page keeps every overlay (hints, panel, room card, Settings, Jobs, Proposals, the wizard, the build form, notices) below it while the scene still draws behind it. Out of full screen (Ctrl+Cmd+F) the window is 1440 by 900, or 85 percent of a smaller screen, and no smaller than 1100 by 700. Only `http://127.0.0.1:<port>` loads in the window (an ATS exception for that address only); other links open in the default browser. Launched as a login item, it starts hidden: the daemon runs and the window waits; with the widget on, the widget shows. With "When the app opens: only the widget" (below), an ordinary open shows the widget and not the house; the Dock icon and the menu still open the house.

**The page's API.** A user script defines `window.pywebview.api`, the same object `vision ui` provides, so the page needs no change. Every method returns a promise: `token()` (the token, read from `$VISION_HOME/token`; never in a URL), `chooseFolder()` (an absolute path or null), `micStatus()` and `requestMic()` (`"granted"`, `"denied"`, `"restricted"` or `"undetermined"`), `openSystemSettings(pane)` (`"microphone"`, `"login-items"` or `"files-and-folders"`; true when opened), `loginItemEnabled()` and `setLoginItem(enabled)` (a boolean), `restartDaemon()` (true once the daemon the app owns answers again, false if the app does not own it), `appInfo()` (`{name, version, bundleId, ownsDaemon}`) and `quit()` (quits the app, which stops the daemon it started; the window shows a Quit control in the panel and in Settings, This Mac, only when this method exists, and asks before calling it). For the widget and the shortcuts: `widgetPrefs()` answers `{widget, openWith, summon, talk, shown, shortcuts: [{id, label}], status: {summon: {registered, problem}, talk: {registered, problem}}}`, where `widget` is a boolean, `openWith` is `"house"`, `"widget"` or `"menubar"`, `summon` and `talk` are a shortcut id or `"off"` and `problem` is null or a sentence for the owner; `setWidgetPrefs(changes)` takes any of `widget`, `openWith`, `summon`, `talk`, applies them (registering the shortcuts again) and answers the same shape; `showWidget(shown)`, `dismissWidget()` (the keyboard goes back to the app in front; the widget stays if it is on), `openHouse()` and `fitWidget(height, [x, y, width, height])` (the widget page's height and its drag handle) answer true; `goToBackground()` (the panel's **Minimize**: the house window closes and the app stays in the menu bar) answers true, and `safeAreaTop()` answers the inset in points. Both pages get the same bridge; `web/src/net/native.ts` feature-detects every method, so a plain browser and an older app show none of what needs it. Only the main frame on the daemon's origin is answered.

**In the background.** The widget is a 380-point-wide non-activating `NSPanel` at the floating level, on every Space and over full-screen apps (`canJoinAllSpaces`, `fullScreenAuxiliary`), that never hides when the app is not in front. Showing it leaves the app in front where it was; clicking it, or the summon shortcut, gives it the keyboard without activating the app, and Cut, Copy, Paste, Select All, Undo and Redo work in it all the same. It shows `/widget.html` from the daemon in a WKWebView with the same bridge, kept to the daemon's origin, and a line of its own while the daemon starts or after it stops. The page asks for its height (from 96 to 560 points) and the panel keeps its top edge; it is dragged by the name and state, and its top-left corner is remembered for each arrangement of screens (in the app's user defaults); after a change of screens it goes back to where it was on that arrangement, or onto the screen it overlaps most. Hiding it, like closing the house, never stops the assistant.

The widget page (`web/widget.html`, `web/src/widget.ts`, `web/src/hud/widget/`) is a second page built by Vite beside the house, with the same connection, store, composer, keys and gate card and no scene. It shows the assistant's name and state (idle, listening, thinking, speaking, connecting or offline: a dot and the 1px border, mustard while busy, red while offline), the oldest request waiting for a yes with Yes, Not now and how many more wait, the latest exchange (the reply from its first word, scrolling inside, fading at the bottom while there is more), the message field (Enter sends, Shift+Enter is a new line, Up in an empty field recalls the last message, Escape interrupts a speaking assistant or else dismisses the widget) and hold to talk. House opens the house; Hide hides the widget. Before the first exchange it shows the last turn from `/api/history`. `?mock=1` plays the mock daemon, for screenshots.

Two global shortcuts are Carbon hot keys (`RegisterEventHotKey` with `kEventHotKeyExclusive`), which reach the app from any other app without the Accessibility permission an event monitor or event tap would need. Summon (default Option+Space) brings the widget up with the cursor in its field, or, pressed while it has the keyboard, sends it away. Push to talk (default Control+Option+Space) shows the widget without taking the keyboard and, through `window.visionWidget.talk(down)`, has the page send `input.ptt` with `down: true` on key down and `false` on key up, as the house's hold to talk does; the widget shows that it listens. Each is chosen in Settings, This Mac, "Widget and shortcuts", from a short list (Option+Space, Control+Option+Space, Shift+Option+Space, Control+Shift+Space, Shift+Command+Space, Control+Option+V, Control+Option+T) or Off. One that another app holds, that macOS refuses, or that matches the summon shortcut is not registered, and Settings says why; one macOS also uses (`CopySymbolicHotKeys`) is registered with a warning. The same block turns the widget on or off (off: it waits for a shortcut or the menu) and sets what the app shows when it opens. These are the shell's own preferences, kept in its user defaults.

**While it runs**, it polls `/api/state` every two seconds for the menu bar item. Its menu has the assistant's name and state first (idle, listening, thinking, speaking or not running), then Open the house, Show widget or Hide widget, the three listening modes (Hold to talk, Listen for its name, Listen always) with a check on the current one, chosen there through `PATCH /api/settings` (a refusal is shown in the daemon's words), Start at login and Quit. The armchair is a template image, so macOS tints it for a light or a dark menu bar, and it carries a small dot while `listen.mic` is not `closed` (as of the last poll). The global talk shortcut reaches the daemon through the widget's page, which is loaded whenever the daemon answers, so in `hold` it opens the microphone with the widget hidden and the house closed (it shows the widget) and the release closes it. If the daemon stops answering or its child exits, the window says so and offers to restart it.

**In the menu bar.** Closing the window (Cmd+W, or **Minimize** in the panel beside Quit, through `goToBackground()`) tears down the window and the page and makes the app's activation policy `.accessory`: no Dock icon and not in the app switcher, while the daemon, automations, the phone channel, the widget (a non-activating panel, which works under either policy and stays shown through the switch) and the shortcuts (Carbon hot keys, which do not depend on the policy) keep running. The app also starts as `.accessory` and becomes `.regular` when the house opens: from the menu bar item, the widget's House, opening the app again, or at launch with "When the app opens: the house". "When the app opens" can also be "only the widget" or "only the menu bar".

**On quit** (Cmd+Q), the app stops the daemon only if it started it: SIGTERM, then SIGKILL after five seconds. A daemon started by `vision run` or the LaunchAgent is left alone.

**Permissions.** macOS attributes a child process's privacy access to the app that started it (the responsible process), so the microphone and folder prompts name the app, using its `NSMicrophoneUsageDescription` and folder usage strings. The bundle carries the audio-input entitlement.

**Start at login** uses `SMAppService.mainApp`. If the system refuses to register the ad hoc signed app, the app writes a per-user LaunchAgent, `org.openquestai.vision.login`, that runs `open -g -j -a <app> --args --login`. The menu toggle, the page's `setLoginItem` and `<app> --login-item on|off|status` (used by setup and doctor) all go through the same code.

**Self-test.** `<app> --self-test <result.json>` uses a throwaway home with voice off, the fake brain and a free port, and keeps the shell's preferences in memory. It opens a normal window, waits until the page reports that it is connected and that every bridge method exists (none is called), then does the same for the widget's page, shows and hides the widget, minimizes the app to the menu bar and opens the house again, recording the activation policy and whether the window was open each time (`menu_bar`), records whether each shortcut registered or why not (`widget` and `shortcuts` in the result), and the safe-area inset of the window and of each screen (`safe_area`). It lets the shortcuts go, writes the result, stops the daemon and quits, in about three seconds; it passes when both pages connected and the widget showed and hid. `vision app build --out <folder>` builds a test copy elsewhere than `dist/`.

**Standalone.** `vision app build --standalone` puts everything the daemon needs into `Contents/Resources`, so the app runs on any Apple Silicon Mac with macOS 14 or later:

- `python/`: a copy of the relocatable Python the project's `.venv` was made from (uv's build, which finds its library through `@executable_path`), with every locked dependency and every extra installed by `uv pip install` from `uv export --frozen --all-extras`, then `vision` itself, not editable. Left out: Tk, IDLE, pip, headers and static libraries, test folders, compiled-code sources and entry-point scripts; the build configuration no longer names the builder's folders. MLX keeps its headers, which it reads at run time. Bytecode is compiled fresh with hash-based checks, so it stays valid wherever the app is copied, and the daemon runs with `PYTHONDONTWRITEBYTECODE`, so nothing is written into the signed bundle.
- `house/`: the default house, the tool catalog and the personas.
- `web/dist/`: the built window, both pages (the house and the widget); the build stops if either is missing.

Info.plist then says `VisionStandalone = true`, names no project, and sets the home to `~/.vision`, expanded on the Mac it runs on. The shell runs `Resources/python/bin/python3.12` with `VISION_RESOURCES` pointing at `Resources` and the home as its working directory, so `vision.core.resources` finds the house and the window in the bundle and the key is never read from a `.env` file. Every Mach-O file in the payload is signed ad hoc before the bundle is sealed, so `codesign --verify --deep --strict` passes and the identity stays `identifier "org.openquestai.vision"`. User data stays in `~/.vision/` and models in the Hugging Face cache; replacing the app touches neither. `vision app package` zips the standalone app with `ditto`, which keeps the signatures, as `dist/<name>-<version>-macos-<arch>.zip`. The thin build stays the default for development.

On another Mac the app is quarantined and is not signed with a Developer ID, so macOS blocks its first open until it is approved once in System Settings, Privacy and Security (Open Anyway), or the flag is removed with `xattr -dr com.apple.quarantine`. An app built on the same Mac is not quarantined.

### 4.11 Settings, the first-start wizard and reset: `vision/settings/`, `web/src/hud/settings/`

**Settings** opens with Cmd+, (Ctrl+,) and holds everything a person can change, in twelve groups:

| Group | Fields |
|---|---|
| Assistant | The name, up to 40 characters; the host carries it. About you: what to call the owner, the business and anything else to keep in mind (`owner.name`, `owner.business`, `owner.notes`, section 4.4), written to `owner.md` in the vault, not `config.toml`, and applied from the next turn. |
| Library | The documents with title, kind, size and when added; add by choosing files or dropping them on the group, or by pasting text with a title; open one to read its text; rename; remove after a confirmation; every refusal beside the action that drew it, and where the files live. |
| Models | Talk and heavy models with their efforts, the monthly cap with this month's spend, offline mode, and the local model: backend, model, server address, the catalog marked for this Mac with downloads and deleting, and a server test. The list of Claude models comes from the Models API (cached an hour), else a built-in list, with prices and the effort levels each takes (`efforts`). |
| Agents | Name, model, effort and heavy effort of each non-host agent. The host has none of its own. |
| Rooms | Per room: name, agent (fixed for the Hall), project name, project folders (up to eight, added and removed one at a time), tools, model. Added rooms can be removed. |
| Voice | On or off, When it listens (`hold`, `wake`, `always`, each with one line on what the microphone does; the follow-up window shows only for `wake` and `always`; `always` while `shell` is free, or the other way round, asks first: "With Always on and shell commands Free, anything said in the room can run commands on this Mac without a card."), the line about one Bluetooth headset as microphone and speakers in a listening mode, the microphone permission, input and output devices (listed fresh on opening, on Refresh and when the window gets focus back; a chosen device that is gone shows as not connected), the speaking voice (one of eleven) with a test sentence (`POST /api/voice/speak`, the unsaved voice and speakers allowed; it opens no microphone), the follow-up window (0 to 300 s), the speech-models download and a three-second test. A silent microphone is reported as the device, with Try again; when the app's own permission reads granted, the screen does not send the owner to System Settings. A device change after a failed start retries the microphone loop. |
| Asking first | `free`, `ask` or `never` per tool; `free` is locked for `start_project`. Choosing `free` for `shell` or `run_program` asks for a confirmation first; Shell's note says free holds only at the Mac, and Run a program, listed right after it, says free holds only in jobs the owner started at the Mac (section 4.5). |
| Automations | The list, a form to create or edit, pause, resume, run now, delete (section 4.12). |
| Phone | The bot token (write-only), pairing code and unpair, what is sent to the phone (always, when away or never per kind), whether the owner is at the Mac now and the away time (1 to 120 minutes, sent as `away_after_s`), and the tools the phone may approve (section 4.13). |
| API key | Where the key is kept, and a field to add or replace it. |
| This Mac | Start at login (through the app's bridge, section 4.10), restart, run setup again, and the doctor's checklist with Fix for the downloads and the window. |
| Reset | The three levels and the backups. |

Each group saves on its own with `PATCH /api/settings`, sending only what changed. Every field is checked and all problems come back together as a 400 with `{errors: [{field, message}]}`. Config fields are written to `config.toml` (`[assistant] name` and `setup_completed`, `[brain]` models, `[budget] monthly_cap_usd`, `[voice]` devices, voice and `followup_window_s`, `[gate.tiers]`, and `[jobs]` `max_running`, `max_steps`, `job_timeout_s`, `max_job_usd` and `speak_results`, sent as `jobs.timeout_s` and so on; the window has no group for them yet; and `[presence] away_after_s`, sent as `presence.away_after_s`, which the Phone group sets through `PATCH /api/phone`); agent names and models go to `house.toml`. The assistant, budget, voice, gate, automations, jobs and presence sections apply to the running daemon at once, and so do offline mode, the local model and the host's efforts (`models.offline`, `models.local`, `models.local_backend`, `models.local_server`, `models.talk_effort`, `models.heavy_effort`); a change of Claude model needs a restart, and the answer says which (`{changed, applied, restart, settings}`). Turning offline mode on is refused (400, field `models.offline`) until the chosen MLX model is downloaded, or the server answers and lists the model; an MLX model must be a Hugging Face repo. A change to offline mode or the local model publishes `brain.mode` and a notice.

**Local models.** `GET /api/local-models` answers `{taken, memory_bytes, recommended, models, chosen, custom, offline}`: each catalog entry with `fit`, `on_disk_bytes` and `download` (`{state, done_bytes, total_bytes, message}`); `chosen` is `{backend, model, server, tools}`; `custom` is the chosen MLX model when it is not in the catalog. `POST /api/local-models/download {repo}` fetches any Hugging Face repo in the background (no cancel: the Hub client cannot stop one); `POST /api/local-models/delete {repo}` removes it from the Hugging Face cache, never the model offline mode uses, and answers `{deleted, freed_bytes}` with the listing; `POST /api/local-models/server/test {server?}` answers `{ok, models, message}`.

The API key is write-only. `POST /api/settings/key` checks its shape, stores it in the Keychain, verifies it by listing models, and answers `{stored, source, verdict}`; the key is never sent back, and the field is cleared at once. A first key works at once; replacing a key needs a restart.

**The first-start wizard** opens over the house when `GET /api/settings` reports `setup.first_run`: no key is found anywhere, or `[assistant] setup_completed` is not true. It has eight steps: welcome; the API key; downloads (the local model, about 2.1 GB, and the speech models, about 2.0 GB, each started by a click and run in the background); the microphone permission and test; the assistant's name; About you, in the assistant's voice ("What should I call you?", "What business are we running?", "Anything else I should know?", all optional, saved as `owner`); one project room (its folders); a summary. `vision setup` in a terminal asks the same three questions after the name and cap (Enter keeps an answer, `-` clears it), and asks for one folder at a time and adds it to the room's list. Only the summary's Finish marks setup completed; Later or Escape closes it unmarked. This Mac, Run setup again, opens it any time, and a full reset opens it again. `vision setup` in a terminal sets the same flag when it ends (section 4.9).

**Reset** has three levels, each taking a backup first:

| Level | Removes | Then |
|---|---|---|
| `settings` | `config.toml` | Defaults apply at once; a restart is asked for only if a restart-only value changed. |
| `house` | `house.toml` | The default house reloads. |
| `everything` | Both, the memory vault (with the owner's profile, the library's documents, their originals and its search index), `log.db` with its `-wal` and `-shm`, the images the owner sent (`images/`), `budget.json`, `automations.json` | Memory is reopened with the personas seeded again, budget and automations reload, a restart is asked for, and the wizard opens. With `remove_key`, the Keychain key is deleted too. The window asks you to type the assistant's name first. |

**Backups** go to `$VISION_HOME/backups/<YYYYMMDD-HHMMSS>-<level>/` (0700, with `-2`, `-3` if the name is taken) with a `manifest.json` listing what was copied; only items that exist are copied, and the key never is. Restoring one first backs up the current copies of the same items (level `restore`), then puts the backup's items back and reloads the same way. Backups are never pruned.

### 4.12 The scheduler: `vision/scheduler/`

An automation is an instruction the assistant carries out by itself at set times. Each run is a conversation turn with the source `automation`: the brain is told the automation is due and that nobody typed or said it, no `user.utterance` is sent, and a shown-only automation's reply is not spoken.

**Stored** in `$VISION_HOME/automations.json` (0600, `{"version": 1, "automations": [...]}`), written whole through a temporary file and a rename; a file that cannot be read is moved to `automations.json.broken` and the list starts empty. An automation has an id, a unique name (up to 60 characters), an instruction (up to 1,000), a schedule, whether it speaks, whether it is paused or finished, its next run, and its last five results (`ok`, `failed`, `interrupted`, `needed_approval` or `missed`, each with how it was triggered: `schedule`, `catch_up` or `manual`). At most 50.

**Schedules**, all in the Mac's local time, with stated rules for daylight-saving changes:

| Kind | Fields |
|---|---|
| `once` | `at` (`YYYY-MM-DDTHH:MM`) or `in_minutes`; kept as finished after it runs |
| `daily` | `time` (`HH:MM`) |
| `weekly` | `days` (mon to sun), `time` |
| `interval` | `every` and `unit` (minutes or hours), at most a year, counted from when it was set |
| `cron` | `expr`, five fields; must fire within eight years |

**The runner** runs one automation at a time and waits while a turn is running, someone is speaking or being transcribed, or a gate card is waiting. Run now goes first. A run missed by more than `[automations] missed_grace_s` (default 3,600) is recorded as `missed`; a later but still recent one runs once as `catch_up`. Typed input waits behind a run like behind any turn (section 6); speech, Escape, Cmd+Enter and Send now interrupt it.

**Tools and safety.** The assistant manages automations with the seven tools in section 4.5. Nothing an automation does goes around the gate: during its own run it cannot create, change or delete automations, and an `ask` tool that nobody answers does not run and marks the run `needed_approval`.

**Routes and events.** `GET /api/automations` returns `{automations, limits, timezone, now}`; `POST`, `PATCH /{id}`, `DELETE /{id}` and `POST /{id}/run` change them (a refused change is a 400, an unknown id a 404; routes take ids, never names). Every change publishes `automation.changed` and a `notice`; runs publish `automation.started` and `automation.finished` (section 5).

### 4.13 Phone: `vision/remote/`

The owner can message the assistant from a phone through a Discord bot of their own. The daemon only connects outward; nothing on the Mac listens for the internet.

**Structure.** A transport interface (receive a message, send text, send buttons, edit, acknowledge a press, show typing, fetch an attachment, send a voice note) with one implementation, Discord. Pairing, commands, turns, notifications and approvals sit above it and know nothing about Discord.

**Discord.** The Gateway over `websockets` (API v10, intent `DIRECT_MESSAGES` only): heartbeat with jitter, a missed acknowledgement closes and resumes, back-off from 1 s to 60 s, and close codes 4004 and 4010 to 4014 stop the channel with a notice. The HTTP API over `httpx`, with the bot token in the header only, rate-limit headers and 429 `retry_after` obeyed. Direct messages only; servers are ignored.

**Pairing.** Settings shows a six-digit code that lasts ten minutes and is used up by a match or by five wrong tries. The paired owner's user id and DM channel are kept in `$VISION_HOME/phone.json` (0600, backed up and cleared by Start over). Anyone else gets one fixed line at most once a minute, runs nothing, and is written to the audit log without their words.

**Token.** In the Keychain (service `vision`, account `phone_bot_token`), checked with `GET /users/@me` before it is stored. It is write-only from the window and never logged, returned by a route, written to `phone.json` or put in a backup.

**Turns.** A message from the owner is a turn with the source `phone`, run only while the assistant is idle (five may wait; everything that waited goes as one turn with one reply, section 6), through the same brain, memory, tools, budget and log. Replies are escaped, split under 2,000 characters and not spoken on the Mac unless the setting is on. `status`, `stop` and `help` are commands; none goes around the gate. Voice notes are decoded by `soundfile`, `afconvert` or `ffmpeg` (none required) and transcribed by the local Whisper. Images the owner sends in the DM (any attachment that is not a voice note, up to six per message) are fetched from Discord's attachment hosts only (`cdn.discordapp.com` and `media.discordapp.net`, without the bot token, like voice notes; any other host is refused), then checked, cleaned and kept like an image from the window (section 4.2), and every accepted one goes with that message's turn: the text is the message, and images alone are put as the owner sending them. What could not be used gets one line saying why; a message with nothing usable and no words gets "I can read text, voice notes and images (PNG, JPEG, GIF or WebP); other attachments are not read." A command word with an image is a message, not a command.

**Presence** (`vision/presence/`). The owner is away when the Mac has had no keyboard or mouse input and no speech to the assistant for `[presence] away_after_s` (default 300, 60 to 7,200, applied at once), when the screen is locked, or when the main display sleeps. It is read through CoreGraphics with `ctypes`, with no macOS permission: `CGEventSourceSecondsSinceLastEventType` (combined session state, any input), `CGSessionCopyCurrentDictionary` (`CGSSessionScreenIsLocked`) and `CGDisplayIsAsleep`; a read costs about a third of a millisecond after the frameworks load once (about 40 ms). It is read every five seconds and fresh before each decision; spoken or typed input to the assistant at the Mac counts as presence, a phone message does not. When the Mac will not say (no login session), the owner counts as present, the event says `known: false`, and `assistant_status` says so. A change publishes `presence` (section 5); `GET /api/state` and `GET /api/phone` carry it.

**Who hears what.** What the owner types on the phone is answered on the phone, and the turn is in the app's thread and history through the same session and memory. What the owner types or says at the Mac is answered at the Mac; nothing goes to the phone, whether or not the owner has left meanwhile. Anything the assistant does by itself reaches both the app and the phone, whether the owner is at the Mac or not.

**Notifications and approvals.** Each kind of message the assistant sends by itself has a choice, `always` (the default for every kind), `away` (only while the owner is away) or `never`, for an owner who wants less: automation results (`notify_automations`), warn and error notices (`notify_warnings`; notices about the channel itself stay in the app), gate requests (`notify_approvals`), the host's report of every finished job wherever it was handed off (`notify_jobs`; one handed off from a phone turn reports there unless `never`), and `send_to_phone` (`notify_assistant`). A line that an agent's proposal waits at the Mac follows the approvals choice and carries no buttons (section 4.16). Presence is read only for a kind set to `away`. A `phone.json` from before (version 1) keeps working, true read as always and false as never. The result of a turn in which `send_to_phone` already messaged the phone is not sent again. Each message has a key (`job:<id>`, `turn:<id>`, `automation:<id>:<started>`, ...) and is sent at most once; one that cannot be delivered is tried again after 5, 20 and 60 seconds, then dropped with a notice in the app, never queued longer. A request has Yes and Not now buttons only for a tool on the phone list and only when its detail fits in full. The list holds by default every tool, the residents' included, but `shell`, which is never approved from the phone (and a free `shell` still asks, at the Mac, during a phone turn), `run_program`, which runs code from a project and is approved from the phone only once the owner adds it, and the made tools (`made_<name>`, section 4.16), which are approved at the Mac only; a `phone.json` saved before a tool existed does not hold it. A press must come from the paired owner in the DM, for a request still open, and becomes the same `gate.decision` the window sends.

**On purpose.** `send_to_phone(text)` (free, the host's only) sends a message to the paired phone at once, whatever the away state, unless `notify_assistant` is `never`; it answers plainly when no phone is paired, the channel is off or has no working token. Its description says to use it when the owner asks for something on their phone and in an automation that should ping them, and that replies, job reports and automation results already reach the phone by the choices above.

**In the window.** Everything stays in the thread and the history. What arrived while the window was not being looked at (the page hidden or without focus, or the owner away per `presence`) sits under a quiet divider, "While you were away" with the count, above the first such entry; the thread opens expanded to it when the owner is back and drops the divider after six seconds in front of them.

**Routes.** `GET` and `PATCH /api/phone` (`notify` takes a choice per kind; `away_after_s` is written to `config.toml` as in Settings), `POST /api/phone/token`, `POST /api/phone/token/verify`, `POST` and `DELETE /api/phone/pairing`.

**Run against the live service:** pairing, text turns, a hand-off from the phone and its report. **Not yet:** voice messages, the approval buttons under real latency, and the Gateway's resume. They are tested against a local fake (`vision/testing/fake_discord.py`), which the presence rules and retries are tested against too.

### 4.14 Knowing the house: `vision/aware/`

The assistant knows its house, the other agents, the work in progress and its own setup.

- **A summary in context.** The rooms, one line per agent (name, role, rooms, model, and what it is doing: free to take work, working on a job, or waiting for the owner's yes), a line naming each room's project name when any room has one, a line naming each room's project folders when any room has some, and the limits of this build ride on the user's message, never on the cached system prompt. After it come two lines from `vision.memory.surroundings_line`: who the owner is now (what to call them and their business, in a few words) and how many documents the library holds. It is sent on the first turn, whenever it changes, and every eight turns.
- **Three read-only tools** (section 4.5): `house_overview` (every room with its project name and current jobs, every agent with what it can do at work and its current job), `room_details` (matched loosely by name; lists the room's project name and folders, its tools and whether each works, the jobs in it now and, for the Library, its notes) and `assistant_status` (models, spend, voice, automations, the residents' jobs and limits, phone and paths; no secrets). `room_details` for the Library lists its documents with title, gist and size.
- **Offline.** In offline mode the summary and `house_overview` add that the host and the residents run on the local model, that nothing goes to Anthropic, that the scout cannot search or load pages, and, for a model without tools, that nothing can be handed off or looked up. `assistant_status` names the local model, why it answers and whether it can use tools.
- **Web work goes out at once.** The limits line, the `hand_off` description and the host's persona tell the host to hand anything that needs the web to the scout at once, tests and reviews to the checker and code to the maker, and to say it is under way, without asking whether to; `open_url` only puts a page on the Mac's screen.
- **Learning, in the same words everywhere.** `limits.learning_line()` rides on the summary and `house_overview`: every agent keeps procedures (no yes needed), may propose a new tool or a change to its own persona, model or thinking level (the host for a resident too), a proposal does nothing until the owner approves it in the window (a yes in the conversation, by voice or from the phone does not approve it), made tools run confined to what the owner allowed, nobody can change the approval rules, their permissions, spending caps, keys, the phone's approval list or the assistant's code, and a refusal is never worked around. The session's preamble adds how many proposals wait and the host's own procedures (section 4.16).
- **Limits in one file.** `vision/aware/limits.py` tells the truth of this build from `vision/residents/abilities.py`: every resident can take work; what each can use at work; that project tools work only when the workbench is installed and the room has a project folder that can be used; that only the host opens apps and links, runs the shell, changes automations and hands out work; and that the envoy has no mail or messaging access yet. The host is told to say so plainly when asked for something nobody can do.

### 4.15 The house at work: `vision/jobs/`, `vision/residents/`, `vision/workbench/`

The host orchestrates and runs no other room. Only the host talks to the owner and hands out work; residents never take orders from each other. Everything goes through a job board that the daemon runs.

**A job** has an id (eight hex characters), a title (up to 80 characters; the brief's first line when none is given), a brief (up to 8,000), the agent id, the room id (or none), a status (`queued`, `working`, `done`, `failed`, `cancelled`), who asked (`host`, `owner` for a job started from the window, or the id of the resident whose request it is), the parent job for such a request, `careful` (use the agent's heavy model), `via` (where the host was asked: `text`, `voice`, `phone`, `automation`; `window` for the owner's), created, started and ended times, the result (up to 20,000 characters), an error, `needed_approval`, its own cost in dollars, and its steps. A step has a time, a kind (`started`, `tool`, `progress`, `request`, `finished`) and up to 300 characters of text; a job keeps its first step and its newest 199.

**Stored** in `$VISION_HOME/jobs.json` (0600, `{"version": 1, "jobs": [...]}`), written whole through a temporary file and a rename after every change, coalesced so one write runs at a time. A JSON file in the style of `automations.json` rather than SQLite: a few hundred small records are held in memory anyway, the file stays readable by hand, and it is backed up and reset with the others (`everything`; work in progress is cancelled first). Every open job and the newest 200 ended ones are kept. A file that cannot be read is moved to `jobs.json.broken`. On start, a job still `queued` or `working` becomes `failed` with "The daemon restarted before it finished."

**The board** (`board.py`) checks a hand-off: the agent exists (by id or name) and is not the host; the room, when given, exists (found by id, name or project name, ignoring case; a project name two rooms share is refused, naming both) and is not the Hall (a resident may work in another agent's room, where the project the work is about lives, in that room's folders), else the agent's first room in plan order; the brief is not empty; the residents can work now (in offline mode the local model is on disk and can call tools; with the month's budget used up, the local model can take the work, else the refusal says why); fewer than `max_queued` jobs wait. It runs at most `max_running` top-level jobs at once and never two for one agent; the rest wait in the order they came. It stops a job at `job_timeout_s` and records what was done so far. Cancelling a working job cancels its task (the gate request it waits on is audited as cancelled, a program it runs is killed with its process group) and then the request it made; a waiting job is simply marked. Every top-level job that ends is handed to the reporter.

**Limits,** `[jobs]` in `config.toml`, applied at once:

| Key | Default | Range in Settings |
|---|---|---|
| `max_running` | 2 | 1 to 6 |
| `max_queued` | 20 | (file only) |
| `max_steps` | 24 | 1 to 200 |
| `job_timeout_s` | 900 | 30 to 14,400 (`jobs.timeout_s` in Settings) |
| `max_job_usd` | 1.00 | above 0, up to 50 |
| `speak_results` | true | true or false |
| `web_search_max_uses` | 5 | (file only) |
| `web_fetch_max_uses` | 5 | (file only) |

**A resident at work** (`vision/residents/`). A job runs as the resident's own session, apart from the host's conversation, through the same stack as the host's brain: the official `anthropic` SDK, streamed with `get_final_message`, the refusal fallback (`server-side-fallback-2026-07-01`, `fallbacks: "default"`) on the models that take it, the system prompt cached with an explicit breakpoint and the transcript with top-level automatic caching, thinking left at the model's default, effort `medium` (`high` when careful), at most 8,192 output tokens (16,000 when careful), and every call charged to the monthly budget and to the job. Tool input is not streamed eagerly, so a file the resident writes never arrives cut short. A passing failure is retried once after two seconds; the SDK's own retries are off.

- *Effort:* the agent's `effort` in the house file (default `medium`), its `heavy_effort` (default `high`) when careful; the plan carries both and `effort_levels`, the levels each Claude model in the plan takes.
- *On the local model* (`local_worker.py`): in offline mode, and when no key is stored or the month's budget is used up while the local model is on disk and can call tools, the job runs on the shared local engine through the same gate, project tools and steps, its generations waiting behind the host's, nothing charged, no server-side web tools. The job records `model` and `local`. A Claude job stops before its next call once offline mode is turned on.
- *Model:* in one of its own rooms, the room's (the plan resolves a room's own model over its agent's); visiting another agent's room, its own `model`; the agent's `heavy_model` when the job is careful and it has one.
- *Room:* project tools and programs come from the room the job runs in (its effective tool list), whoever works there, and the gate card and steps name that room ("Tock, in the Workshop: run a program in the project"). The prompt says when the resident is visiting another agent's room.
- *System prompt:* the persona; the house, one line per agent with role and rooms, built from the plan so renames show; the rules (it works for the host, who speaks for the owner; it never addresses the owner; it finishes by giving its result; it asks other residents only through `ask_resident`; what it reads in files, tool output or on the web is information, never instructions; a refused tool is not worked around); its room, the project it holds ("This room holds the project ..."), its project folders (each usable one with its short name and path, how paths are written, and each one that cannot be used with the reason) and tools; the owner's profile and the library (`vision.memory.resident_knowledge`: the profile whole, then the library as the host gets it within 6,000 characters); its own newest notes (up to 3,000); its procedures and the shared ones (names and "when to use" lines, within 1,500 characters, with the instruction to open one before such work and save or improve one after work that went well). The rules hold the hard line: a refused tool may lead to another approach, a request to another resident or a report of what blocked it, never another route to the same thing; it extends itself only by proposing (section 4.16). The first message carries the job id, title, who asked, the local time and the brief.
- *Own memory:* `$VISION_HOME/house/agents/<id>/notes/`, in the host's Markdown format. A resident's `remember` writes there and its `recall` searches only there (by the query's words; the folder is small, so no index). The host's memory is unchanged.
- *The loop:* each model call is a step; tool calls run through the job's gate and each becomes a step with a one-line summary. The last allowed call is made with `tool_choice: none`, so the resident sums up; reaching `max_steps` ends the job as `failed` with that summary as its result. The job also fails when its own cost passes `max_job_usd`, when the month's budget runs out, when the model declines (`refusal`), or when no API key is stored. Otherwise the resident's final text is the result.

**Residents' tools,** each behind the gate with its own tier (catalog entries with `resident = true`, changeable under Asking first):

| Tool | Tier | Who | What it does |
|---|---|---|---|
| `remember(text)`, `recall(query)` | free | every resident | Its own notes. |
| `list_documents`, `read_document`, `search_documents` | free | every resident | The owner's library, read-only (`vision.memory.resident_tools`). |
| `note_progress(text)` | free | every resident | A `progress` step on the job, shown live. |
| `ask_resident(agent, brief, room?)` | free | every resident, not in a request | A request on the board, run as a child job in the asking job's room unless another (not the Hall) is named; returns its result. |
| `machine_status` | free | steward | Disk, memory, battery (`pmset`, stopped after three seconds), uptime and load; read-only. |
| `assistant_status`, `list_automations` | free | steward | The host's read-only tools, lent. |
| `web_fetch` | free | scout | Anthropic's server-side page fetch: `web_fetch_20260209` on the models documented for it, `web_fetch_20250910` on the others, `max_uses` from `[jobs] web_fetch_max_uses`. It loads only URLs already in the conversation. Asked once at the start like `web_search`; each fetch is a step ("Fetched a page: ..." or "Could not load ... (error)"), audited, and costs only the tokens it reads. The scout's prompt tells it to load a page named in its brief itself and to say plainly when one could not be loaded and why. |
| `web_search` | free | scout | Anthropic's server-side search: `web_search_20260209` on the models documented for it, `web_search_20250305` on the others (Claude Haiku 5.5 among them), `max_uses` from `[jobs] web_search_max_uses`. `never` leaves it out; `ask` asks once at the start of the job. Each search is a step, audited, and charged at `[budget] web_search_per_1k_usd` (10 dollars per thousand). |
| `list_files`, `read_file`, `search_files` | free | a job in a room with a project folder | The workbench, inside the room's project folders only. |
| `write_file`, `edit_file` | ask | a job in a room with a project folder | The workbench, in one of the folders; protected files and `.git/` are never written. |
| `save_procedure`, `list_procedures`, `read_procedure`, `remove_procedure` | free | every resident | Its own procedures and the shared ones (section 4.16). |
| `propose_tool`, `propose_change`, `my_proposals` | free | every resident | Proposals for the owner (section 4.16); `propose_change` for itself only. |
| `made_<name>` | the owner's choice | a resident the owner approved it for | A made tool, reaching at most the approved folders that are also folders of the job's room (section 4.16). |
| `run_program` | ask; free only in a job the owner started at the Mac | a job in a room with a project folder | One of the room's installed programs (by catalog id, such as `git` or `python`), in one of the room's folders (`folder`, a folder's short name; the first when left out), with a clean environment, a timeout and an output cap. Its card shows the exact command and that folder's real path. |

`ask_resident` is refused for the host, for the resident itself, after three requests in one job, from a request (depth 1), and when the resident asked is busy: waiting there could leave two residents waiting on each other. A child job runs at once beside its parent, which is blocked, so it does not take a place of its own under `max_running`. No resident ever gets `shell`, `open_app`, `open_url`, the automation-changing tools, the job tools or `start_project`; the list is filtered against `abilities.HOST_ONLY` whatever is offered.

**The workbench** (`vision/workbench/`, built beside this section) gives `project_tools(folders, programs)`, for the room's folders in order. The residents import it in one place (`vision/residents/project.py`) and receive it injected, so their tests use a fake. `programs` maps each of the room's installed project tools to its program's absolute path (found as in `vision/core/programs.py`). Programs start through `run_command` with an explicit environment.

*Paths over several folders.* Each folder has a short name: the last part of its path, made unique within the room when two share one (case is ignored): `~/Projects/shop` and `~/Work/shop-api` are `shop` and `shop-api`; `~/a/app` and `~/b/app` are `app` and `app-2`. Every path a resident gives the project tools starts with a folder's name (`shop-api/src/app.py`), with one folder as with eight, so a path in a resident's notes keeps its meaning when a folder is added. `list_files(".")` lists the folders, each with its top level; `search_files` with `.` searches all of them; a path whose first part is not a folder's name is refused with the names. Every safety rule holds per folder: a path addressed through one folder must stay inside it, and a link from one of the room's folders into another is refused like any link out. The names come from `vision/core/folders.py`, so the workbench and the prompt always agree.

*A folder that cannot be used.* A folder that is missing, or that the workbench refuses (`/`, the home folder or a folder above it), is named in the prompt with the reason; the job works in the others. A refused folder also adds a step. When no folder can be used, the job runs without project tools.

**The host's side.** `hand_off`, `list_jobs`, `job_details` and `cancel_job` (section 4.5) are free, allowed during an automation's run and from the phone. `start_project` (section 4.8) always asks; its first job is a hand-off like any other, asked by the host, in the project's new room, and reported the same way. `hand_off`'s description tells the model when to use it and to write a complete brief. When a job the host or the owner started ends, the reporter queues it and, once the assistant is idle and nobody is speaking (the wait the automations and the phone use), runs a session turn with source `job`. The turn's text says which agent finished which job and how, with the result; the host tells the owner in its own words. It is spoken only when `speak_results` is on and voice runs, and logged with source `job`. The reply goes to the phone by `notify_jobs` (section 4.13): always, when the owner is away, or never; a job handed off from a phone turn reports there unless `never`.

**The gate names the agent.** A scoped gate's request carries `agent`, `agent_name` and `job`, and its summary reads "Tink, in the Workshop: run a program in the project". Audit rows record the agent and the job. A request from a job that nobody answers is refused as always; the job goes on and is marked `needed_approval`. While one waits, the agent's state is `waiting`.

**Events** (section 5): `job.changed` with the job's summary on every change; `agent.state` (`idle`, `working`, `waiting`, with the job); `room.state` `active` for the job's room while it works, back to its previous light afterwards.

**Routes,** behind the token: `GET /api/jobs?limit=50` (1 to 200) answers `{jobs, agents, limits}`: jobs newest first in the `job.changed` shape, every resident's state as `{<agent>: {state, job}}`, and the limits (`max_running`, `max_queued`, `max_steps`, `job_timeout_s`, `max_job_usd`, `max_asks`, `brief_max`, `title_max`). `GET /api/jobs/{id}` answers `{job}`: the summary plus `brief`, `careful`, `via`, `result`, `error`, `cost_usd` and `steps` (`[{ts, kind, text}]`). `POST /api/jobs` takes `agent`, `brief`, optional `room`, `title`, `careful`, with the same checks as `hand_off`, and answers `{job, started}`. `POST /api/jobs/{id}/cancel` answers `{job}`. A refusal is a 400 with a line for people; an unknown id a 404. `GET /api/state` adds `jobs` (the open ones) and `agents`, so a fresh window is right at once. `GET` and `PATCH /api/settings` carry `jobs: {max_running, max_steps, timeout_s, max_job_usd, speak_results}`.

**Not built yet:** the window's views of the board, the steps and the agent states (the daemon serves them); Codex and Gemini as brains; residents that keep a conversation between jobs; the envoy's mail and messaging; jobs that outlive a restart (they are marked failed); waiting for a busy resident instead of refusing; and per-agent budgets beyond the per-job cap.

### 4.16 Agents that learn and extend themselves: `vision/procedures/`, `vision/proposals/`

The owner's decision: three levels, each under the owner's control. Procedures are written notes and need nobody's yes; a new tool and a change to an agent are proposals the owner decides at the Mac, in the window, and nowhere else.

**Procedures** (`vision/procedures/`). Plain Markdown in the vault: an agent's own in `house/agents/<id>/procedures/<slug>.md`, shared ones in `house/procedures/<slug>.md`. A file holds `# <title>`, `When to use:`, `Author:`, `Changed:` (to the minute), `Opened:` and `## Steps`; parsing is tolerant, so a hand-written file with only a heading and text is a procedure. Limits: title 80, when 300, steps 6,000 characters; 40 per agent, 60 shared. An agent saves (creates or replaces, keeping `Opened`), lists, reads (`Opened` counts up) and removes its own; `shared=true` moves it to the shared folder, where only its author or the host may change or remove it; an agent's own procedure shadows a shared one of the same name. The four tools are free. Routes behind the token: `GET /api/procedures` (`{agents: [{id, name, procedures}], shared, limits}`), `GET`, `PUT` (`{title?, when?, steps?}`) and `DELETE /api/procedures/{owner}/{name}` (owner an agent id or `shared`); every change publishes `procedure.changed`.

**Proposals** (`vision/proposals/`). One store, `$VISION_HOME/proposals.json` (0600, version 1, written whole through a temporary file; a broken file moves to `.broken`), keeps every waiting proposal and the newest 200 decided, each with who proposed it, the job and room, the reason, when, the status (`waiting`, `approved`, `declined`) and the decision. At most 3 wait per agent and 12 in all; beyond that the model gets a plain refusal. A new proposal publishes `proposal.changed` and an info `notice`, and, with a phone paired and the approvals choice allowing it, a short line on the phone that says to look at the Mac; the phone never gets buttons for a proposal. Approve, decline and restore exist only as the owner's routes: no tool, no gate request, no `gate.decision` (which a phone press becomes) and no spoken or typed yes reaches them, and the tests prove each of the three is refused. Every decision is audited (`tool` `proposal`, tier `owner`).

*A new tool* (`propose_tool`): a name (`[a-z][a-z0-9_]{2,39}`, not a built-in's), a one-line description, the input as a JSON schema, the script (Python standard library only, run as `python -I -S -B -c`, or POSIX `sh -c`, at most 20,000 characters), its reach (short names of the job room's folders to read, resolved to paths at proposal time; whether it needs the network) and why. A new version of an existing tool may come only from its author or the host, and turns the tool off until the owner decides; declining puts it back as it was. At approval the owner chooses who may use it (its author or every agent) and its tier (`ask`, the default, or `free`). The tool is stored under `$VISION_HOME/made-tools/<name>/`: `manifest.json` (0600) pins each version's sha256, `versions/<n>.py|.sh` keeps each approved text, `runs.json` the newest 50 runs. Before every run the current file is read and hashed and the bytes that were hashed are the bytes that run; a mismatch (or a file changed on disk, noticed at any listing) turns the tool off with `made_tool.changed` and a warn notice, and only going back to a version whose own hash still matches turns it on again.

*Running one* (`made_<name>`): through the gate at its own tier, with a card that shows the input, the folders it may read, the network, the version, the hash and the author; made tools are never approved from the phone. The reach is the approved folders that are also usable folders of the room the job runs in (the host has none), and the network only if approved. Input is checked lightly against the schema and passed as JSON on stdin, `FOLDERS` carries the folders (JSON, short name to path), the working folder is a fresh scratch folder under `made-tools/scratch/` (removed afterwards); 30 seconds, 20,000 bytes of output. The audit row carries the sha256 and version.

*Confinement* (`sandbox.py`): `/usr/bin/sandbox-exec` with a profile built per run from a fixed template (paths only ever as `-D` parameters): deny by default, Apple's `system.sb`, read the system's own folders, the Python runtime and the approved folders, then deny (the last matching rule wins) the assistant's home, the owner's key and login folders (`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config`, `~/.docker`, `~/.kube`, `~/.netrc`, Keychains, cookies, ...) and the workbench's protected file names inside the approved folders, then allow reading and writing the scratch only. No network rule unless approved (then outbound only, never listening); no Mach services beyond `system.sb`'s, so no Keychain, pasteboard, Apple Events or LaunchServices. A launcher sets CPU, file size, open files and process limits before `sandbox-exec`. A shell needs `fork`, so a detached process can outlive its group: two random marker files beside the scratch, one the profile allows and one it denies, let `sandbox_check` find every process of this run, and they are killed when it ends. When macOS cannot confine (no `sandbox-exec`, or a self-check run is not confined) made tools do not run. Not enforced, and said so on the approval card: what the script does with what it may read, where it connects when the network is allowed, memory and the scratch folder's total size, file metadata almost anywhere, the system's own readable files, side channels, and that Apple marks `sandbox-exec` deprecated. `tests/test_proposals_sandbox.py` tries each breakout beside an unconfined control.

*A change to an agent* (`propose_change`): `persona`, `model` or `effort` (thinking level) only; anything else is refused in code (the approval rules, tiers, permissions, spending caps, keys, the phone's approval list and the assistant's own code are the owner's alone). A resident proposes for itself; the host for itself or a resident. `before` is taken when it is proposed; a model must be one in the price table. At approval a model or effort goes through `PATCH /api/settings` (`{"agents": {id: {...}}}`, or `{"models": {"talk"|"talk_effort": ...}}` for the host), a persona is written to the plan's persona file; a refusal is a 400 and the proposal stays waiting. Restore applies `before` the same way and records `restored_at`. A resident's change applies from its next job; the host's persona once the host's brain rebuilds its system prompt (a restart).

**Routes,** behind the token: `GET /api/proposals?limit=50` (`{proposals, waiting, limits}`: waiting oldest first, then decided newest first, summaries without the script), `GET /api/proposals/{id}` (in full), `POST /api/proposals/{id}/approve` (`{who?, tier?}` for a tool), `POST /api/proposals/{id}/decline` (`{note?}`), `POST /api/proposals/{id}/restore`; `GET /api/made-tools` (`{tools, confinement: {available, reason, enforced, not_enforced}}`), `GET /api/made-tools/{name}` (with the script, every version's text and the runs), `PATCH /api/made-tools/{name}` (`{tier?, who?, enabled?}`), `POST /api/made-tools/{name}/versions/{n}/use`, `DELETE /api/made-tools/{name}`. A refusal is a 400 with a line for people, an unknown id a 404. Backups and Reset, Everything carry `proposals.json` and `made-tools/`; the procedures travel with the vault.

**The window.** A Proposals control beside Jobs with the waiting count opens a view with three tabs: Proposals (waiting first, then history; a tool's whole script in a monospace block that scrolls inside itself, its reach and the confinement's two lists, Approve with who and tier, and a warning for free with network; a change's before and after side by side; Decline with a note; Restore for an approved change), Tools (each made tool with its state, version, who, tier and runs; enable, disable, tier, who, a version to go back to, delete) and Procedures (per agent and shared; read, edit, delete). Mock mode covers all of it.

## 5. Protocol

One JSON envelope in both directions: `{"type": "...", "ts": 1731400000.0, "data": {...}}`.

**Daemon to window**

| Type | Data |
|---|---|
| `state.changed` | `state`: idle, listening, transcribing, thinking, speaking; `brain`: claude, local or fake |
| `budget` | `month`, `spent_usd`, `cap_usd` |
| `house.changed` | `revision` (the window then reloads `/api/house`) |
| `user.utterance` | `text`, `source`: voice, text or phone (a job report has none: its turn is the host's own); `images`: `[{id, width, height}]`, the images the message carried (`[]` for none; `text` may then be empty); `ids`: the waiting messages the turn answers together, in order (their words are `text`, one paragraph each; up to six messages and 36 images), `[]` for speech |
| `vision.delta` | `text` (a streamed fragment) |
| `vision.reply` | `text` (the finished reply; for a cut-off turn, what was said of it), `turn_id`, `status`: ok, interrupted or failed (an older window ignores it) |
| `voice.level` | `level` 0 to 1, about 30 times a second while speaking |
| `room.state` | `room`, `state`: dark, idle, active |
| `gate.request` | `id`, `tool`, `summary`, `detail`, `expires_at`; `agent`, `agent_name`, `job` for a resident's request, else null |
| `gate.resolved` | `id`, `decision`: allow, deny, timeout |
| `brain.fallback` | `from`, `to`, `reason` |
| `brain.mode` | `offline`, `answering` (claude, local or fake), `local_backend`, `local_model`, `local_tools` (true, false or null until known), `local_images` (whether the local model can read images; false) |
| `automation.changed` | `id`, `change`: created, updated, deleted or reloaded; `automation` (its `GET /api/automations` shape) or null |
| `automation.started` | `id`, `name` |
| `automation.finished` | `id`, `name`, `status`: ok, failed, interrupted, needed_approval or missed; `reply` (its start) |
| `job.changed` | `id`, `title`, `agent`, `room`, `status`: queued, working, done, failed or cancelled; `asked_by`, `parent`, `created_at`, `started_at`, `ended_at`, `needed_approval`, `model` (empty until it starts), `local`, `last_step` (`{ts, kind, text}` or null) |
| `agent.state` | `agent`, `state`: idle, working or waiting; `job` (or null) |
| `presence` | `away`, `known` (false when the Mac would not say; the owner then counts as present), `reason`: idle, locked, asleep or null; `since`, `away_after_s` |
| `procedure.changed` | `owner` (an agent id or `shared`), `name`, `change`: saved or removed |
| `proposal.changed` | `id`, `kind`: tool or change; `status`: waiting, approved or declined; `agent`, `waiting` (how many wait now) |
| `made_tool.changed` | `name`, `change`: approved, enabled, disabled, updated, deleted or ran; `enabled` |
| `queue.changed` | `items`: every message that waits for the assistant, in the order it will go, the window's lane first: `[{id, preview, images, source, at}]`, `preview` the first 140 characters on one line (for images alone, what they are), `images` how many, `source` text or phone, `at` Unix seconds |
| `notice` | `level`: info, warn, error; `text` |

**Window to daemon**

| Type | Data |
|---|---|
| `hello` | `token` (must be the first message) |
| `input.text` | `text` (at most 20,000 characters), `images` (optional: at most six distinct ids from `POST /api/images`; `text` may be empty only with one), `now` (optional, default false: stop the reply and send at once, behind what already waits), `id` (optional, 1 to 64 of `A-Z a-z 0-9 _ -`: the window's own name for the message, echoed in `queue.changed` and `user.utterance`; the daemon makes one when it is left out). While a turn runs the message waits (section 6); an older window that sends neither field still works, its message waits. An id the daemon no longer has starts no turn and gives a `notice` |
| `input.ptt` | `down`: true or false |
| `input.interrupt` | none (what waits then goes at once) |
| `input.take_back` | `id` of a waiting message: dropped before it is sent; unknown or already sent, nothing happens |
| `input.send_now` | `id` of a waiting message: stop the reply and send it with the messages ahead of it; those after it keep waiting |
| `gate.decision` | `id`, `decision`: allow or deny |

**HTTP.** All need the token in an `Authorization` header.

- Core: `GET /api/health`, `GET /api/state` (with `mode` in the shape of `brain.mode`, the open `jobs`, the residents' `agents` states, `presence` in the shape of its event and `queue`, the waiting messages in the shape of `queue.changed`'s `items`), `GET /api/history?limit=50` (1 to 500; a turn's `source` is voice, text, automation, phone or job, and its `images` are `[{id, width, height}]`).
- Images (section 4.2): `GET /api/images/limits` (`{limits: {types, max_bytes, max_pixels, max_per_message, long_edge}}`); `POST /api/images` with the image as the whole body (the type is read from the bytes; name and `Content-Type` are ignored), answering `{image: {id, media_type, width, height, bytes}}` for the clean copy, or a 400 with one plain sentence; `GET /api/images/{id}` (the file, with `nosniff` and a sandboxing content policy; the window fetches it with the token and shows a blob); `DELETE /api/images/{id}` (`{removed: true}`; 404 when unknown).
- House (section 4.8): `GET /api/house`, `GET /api/house/agents`, `GET /api/house/tools`, `GET /api/house/tools/propose?project=...` (one folder per call), `POST /api/house/rooms` and `PATCH /api/house/rooms/{id}` (each with `folders`, a list of folder paths), and `DELETE /api/house/rooms/{id}`.
- Settings (section 4.11): `GET` and `PATCH /api/settings`, `POST /api/settings/key`, `POST /api/settings/key/verify`, `GET /api/models`, `GET /api/voice/devices`, `POST /api/voice`, `POST /api/voice/test`, `POST /api/voice/speak`, `GET` and `POST /api/downloads`, `GET /api/fs/dirs?prefix=`, `GET /api/local-models`, `POST /api/local-models/download`, `POST /api/local-models/delete`, `POST /api/local-models/server/test`, `GET /api/doctor`, `POST /api/doctor/fix`, `POST /api/reset`, `GET /api/backups`, `POST /api/backups/{id}/restore`.
- Automations (section 4.12): `GET` and `POST /api/automations`, `PATCH` and `DELETE /api/automations/{id}`, `POST /api/automations/{id}/run`.
- Jobs (section 4.15): `GET` and `POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`.
- Procedures and proposals (section 4.16): `GET /api/procedures`, `GET`, `PUT` and `DELETE /api/procedures/{owner}/{name}`, `GET /api/proposals`, `GET /api/proposals/{id}`, `POST /api/proposals/{id}/approve`, `/decline`, `/restore`, `GET /api/made-tools`, `GET`, `PATCH` and `DELETE /api/made-tools/{name}`, `POST /api/made-tools/{name}/versions/{n}/use`.
- Phone (section 4.13): `GET` and `PATCH /api/phone`, `POST /api/phone/token`, `POST /api/phone/token/verify`, `POST` and `DELETE /api/phone/pairing`.

## 6. One turn, end to end

1. The microphone hears speech. VAD closes the utterance. Whisper transcribes it.
2. `wake.py` decides it is for Vision. `user.utterance` is published and the state becomes `thinking`.
3. `session.py` sends the text to the router, which streams it to Claude. A typed or phone message may carry images: the session loads them from the store, names them on `user.utterance` and hands them to the brain with the words (section 4.2).
4. Fragments arrive as `vision.delta`. A sentence splitter hands each finished sentence to `tts.py`.
5. The first sentence plays. The state becomes `speaking`, `voice.level` drives the streaks in the Hall.
6. If Claude calls a tool, the gate decides. A free tool runs. An `ask` tool waits for you.
7. When the reply ends, `vision.reply` is published, the turn is written to the log (with the ids and sizes of its images), and the state returns to `idle` with the 20-second follow-up window open.

**While a turn runs** (thinking, a tool, speaking), the session (`session.py`, `waiting.py`) holds what comes next:

- **Typed messages wait.** Up to five, kept by the daemon and listed in every window (`queue.changed`, `queue` in `/api/state`), so a reload or a second window loses nothing; a sixth is refused with a `notice`. A short yes or no while a gate request waits still answers the request and never waits. `input.take_back` drops one.
- **When the turn ends, however it ends,** everything waiting goes as ONE turn: one `user.utterance` with the words in the order written (one paragraph each), all their images and their `ids`, and one reply. The brain gets, on that turn only: "[The owner wrote these N messages while you were replying, in this order. Answer them together, in one reply: they may add to or correct what you just said.]" (for one: "[The owner wrote this while you were replying. It may add to or correct what you just said.]").
- **Interrupting is on purpose.** `input.interrupt` (Escape, Stop, a stop phrase) stops the turn and what waits goes at once. `input.text` with `now`, or `input.send_now`, stops it and sends that message with the ones ahead of it. Speech stops it too: push to talk pressed (what waits then holds until the words said under it arrive, or two seconds after the release brings none), and in `wake` and `always` an utterance that starts with the name and says something after it, heard over the reply once the echo guard has removed the assistant's own words (so its own speech saying its name never counts). A spoken message goes alone and at once; typed messages that wait go right after it, so speech is never folded into words the owner can still take back.
- **A cut reply** stays in the log and the thread as `interrupted`, with what was said of it. The next turn, whatever it is, tells the brain: "[The owner interrupted your last reply. They heard it only up to: "…<its last 25 words>". Do not carry on from there or repeat it unless they ask; answer what follows.]", or, when nothing of it was heard, "[The owner interrupted you before you answered "<the message>", so they heard no reply to it. Answer what follows; take the earlier message up only if it still matters.]" (the brain keeps no history for a turn cut before it said anything).
- **Order when several wait.** The owner's typed words first (the session starts them before it is idle), then the phone's (its own lane: everything that waited there goes as one turn with one reply, told "[The owner sent these N messages one after another while you were busy, in this order. Answer them together, in one reply: a later one may add to or correct an earlier one.]" when there are several; the two lanes never share a turn), then job reports and automations, which wait for both (`Daemon.busy_after_phone`) and take turns between themselves as each finds the assistant idle. Words typed during a phone, job or automation turn wait for it to end, then go before whatever else waits.

## 7. When things go wrong

| Failure | Behaviour |
|---|---|
| Claude rate limit, auth failure, timeout, offline | One retry, then the local model. Vision says it is running locally. |
| Credits exhausted or monthly cap reached | Talk moves to the local model and stays there. A notice says why and how to raise the cap. |
| No API key stored yet | Vision runs on the local model and a notice asks you to add one in Settings. The first-start wizard asks for it too. |
| Local model also unavailable | Spoken and shown error. The turn is logged as failed. |
| Speech recognition or voice fails to load | Text keeps working. A notice says voice is off and why. Missing speech models are named and never fetched by themselves (section 4.3). |
| Microphone permission missing | A notice with the exact setting to change. |
| Window loses the socket | Reconnects with back-off and reloads state from `/api/state`. |
| Daemon crashes | Under the app, the window says so and offers to restart it; under the LaunchAgent, launchd restarts it. The session resumes from the log. |
| Gate request ignored | Denied after 60 seconds, logged as timeout. |
| A prop fails to load | The room still renders, with a plain stand-in, and a notice. |

## 8. Testing

- **Unit (pytest).** Bus, sentence splitter, wake matcher, echo guard, gate policy and timeout, router fallback with fake brains, memory store and search, config loading.
- **Protocol.** A test client connects to a daemon running the fake brain, sends `input.text`, and checks the event sequence and the log row. It also checks that a wrong token and a foreign `Origin` are refused.
- **Voice.** WAV in, WAV out, with the fake brain: the right utterance is detected, the reply is spoken, "stop" interrupts.
- **House.** Default plan loads; a personal file overrides it; a room with no position lands in the nearest free slot; overlapping, detached, unknown-agent and 21st-room requests are refused; removing a room that would strand another is refused; doors always connect every room to the Hall; a hand edit to the file raises the revision.
- **Tools.** The catalog loads; a proposal on temporary folders finds each marker and the GitHub remote, stays in the top two levels and ignores symlinks; unknown tool ids are refused; a room's tools win over its agent's; the plan carries `tools`; the routes behave, including the 400 for a path that is not a folder.
- **Settings, reset and backups.** Validation and saving of every field, live versus restart, the write-only key, downloads and the doctor with fixes, folder listing, every reset level with its backup, and restore.
- **Scheduler.** Each schedule kind including daylight-saving changes and cron, the store and its broken-file recovery, the runner's waiting, catch-up and missed runs, the tools, and the refusal during an automation's own run.
- **The Mac app.** The Info.plist, paths and builds (thin and standalone) with the compiler, uv, codesign and ditto faked; the resource lookup; and, by hand, the app's self-test, including from a copy outside the repository.
- **Setup.** Every check with the outside world faked (no network, no real `gh`, no Keychain, no microphone), the JSON shape, the exit codes, and scripted runs of `vision setup` with answers fed in, including a second run that changes nothing.
- **Web (vitest).** Store reducers, wall and door geometry from a plan, the tool toggles and the add-room body, the room card's content, the caption's type steps, the spend format, room labels, the settings draft and the wizard's flow.
- **Live checks, done by the orchestrator.** Each "done when" item in section 2 is exercised for real: the daemon under launchd, the window in a browser with screenshots, a real Claude turn on the API credits with the measured time to first audio and its measured cost, a restart-and-recall, a gate yes and no, an offline turn, and a cap set low enough to trip.
- **Yours.** One pass at the real microphone, because nobody else can speak into it.

## 9. Stack

Python 3.12 with `uv`; FastAPI and uvicorn; the `anthropic` SDK; `keyring` for the Keychain; `mlx-lm` for the local model; `mlx-audio` for Whisper, Kokoro and Silero VAD; `sounddevice`; SQLite with FTS5; `pywebview` for `vision ui`. Web: Vite, TypeScript, Three.js. The Mac app: Swift 6, AppKit and WebKit, compiled with `swiftc`, no Xcode project. Exact package versions are checked against current documentation when each part is built.

## 10. Layout

```
vision/            core/ brains/ voice/ memory/ gate/ house/ setup/ settings/ scheduler/ remote/ aware/ jobs/ residents/ workbench/ procedures/ proposals/ macapp/ testing/
web/               src/scene/ src/hud/ src/net/
macos/             Sources/ (the Swift shell), Info.plist template, Vision.entitlements, build.sh
dist/              built apps and packages (not committed)
assets/            models/  textures/  design/
house/             default.toml, tools.toml, agent personas, library template (neutral, no personal data)
tests/
docs/superpowers/specs/
pyproject.toml
```

## 11. Risks, stated plainly

1. **Credits expire.** Each monthly grant runs out a month after it is issued and does not roll over. The grant issued on 2026-11-10 is good until 2026-12-13. Vision treats the credits as a monthly allowance and never assumes a balance carries forward.
2. **Runaway spend.** A loop that keeps calling the model could burn credits. The monthly cap, a per-reply output limit and the audit log bound this. With auto-reload off on the Console, the worst case is that the API stops answering and Vision falls back to the local model.
3. **Latency.** Calling the API directly removes the multi-second start-up that the Claude Code route showed in testing. One test call on 2026-11-12 with the talk model returned its first words in 0.9 seconds on a very small prompt. Measured in file mode (a WAV in, speech written to a WAV), the median from the end of speech to the first audio of the reply is 2.24 seconds, inside the three-second target. A live microphone adds device latency that file mode does not see.
4. **Subscription brains later.** Using Codex and Gemini through their subscription logins in slice 2 raises the same terms question this slice avoids for Claude. It gets checked then, before any code depends on it.
5. **Microphone under launchd.** macOS ties microphone permission to the program that asks. A background agent may need a one-time manual grant. Under the app, the daemon is the app's child and the prompt names the app.
6. **Look.** A modelled house will start plainer than the painted concept on board 04. Lighting, textures and post-processing carry most of the look; furniture fills in room by room.
7. **Going public.** Three things must be settled before the repo is published. The cast: the repo ships original names (Vision as the assistant, then Brass, Wren, Tink, Tock and Rook) and original figures, with no characters from any film or series. The project name: `OpenVision` was ruled out because it is already a known AI project and is taken on PyPI. The public name is OpenQuestAI, chosen on 2026-11-12, when it was free on PyPI, npm and GitHub; the assistant stays Vision and the command stays `vision`. The generated models and textures: each service's terms for the plan in use decide whether they can be redistributed, and that has to be checked before they are committed to a public repo.

8. **An app without a Developer ID.** The standalone app is signed ad hoc, so macOS blocks its first open on another Mac until it is approved once, and it cannot be notarized. Its Keychain item is tied to the bundled Python's ad hoc signature; a rebuilt app with an identical Python keeps access, a changed one may ask for the Keychain password once. Signing with a Developer ID and notarizing would remove both.

## 12. How it gets built

The orchestrator fixes this spec's protocol and layout first, then hands independent parts to Opus and Sonnet subagents: core and protocol, brains and gate, the house, voice, the Mindspace, and memory. Asset generation stays with the orchestrator because it spends credits. The orchestrator reviews every part, runs the tests, and performs the live checks in section 8 before calling the slice done.
