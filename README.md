# OpenQuestAI

OpenQuestAI is a personal assistant that runs all the time on one Mac, for one person: a Python daemon is its mind, and a 3D house seen from above, with the roof off, is its face. You talk to the assistant, called Vision by default, by voice or by typing, and it answers aloud, remembers what you tell it, runs automations you set up, and asks before it does anything risky.

The command is `vision`. No licence has been chosen yet.

## Two ways to run it

- **The standalone app**, for any Apple Silicon Mac. One `Vision.app` holds its own Python, every package, the default house and the window. Nothing else needs installing.
- **From source**, for development. You need [uv](https://docs.astral.sh/uv/), which brings Python 3.12. Node.js builds the window, and Xcode or the Command Line Tools build the app.

Both keep your data in `~/.vision/` and the downloaded models in the usual Hugging Face cache, `~/.cache/huggingface`. Replacing or deleting the app touches neither.

## The standalone app

### What another Mac needs

- **A Mac with Apple Silicon**, running macOS 14 or later.
- **About 5 GB free.** That is about 0.9 GB for the app and about 4 GB for the models it offers to download: the local model (2.1 GB) and the speech models (2.0 GB).
- **Your own Anthropic API key**, from console.anthropic.com.

### Building and packaging it

```sh
uv sync --all-extras
cd web && npm ci && npm run build && cd ..
uv run vision app build --standalone   # dist/Vision.app
uv run vision app package              # dist/Vision-<version>-macos-arm64.zip
```

Copy the zip to the other Mac, open it, and move `Vision.app` into Applications.

### Opening an app not signed with a Developer ID

The app is signed ad hoc, not with an Apple Developer ID. macOS therefore blocks it the first time it is opened after a download, AirDrop or other copy. There are three ways to open it.

- **Build it yourself from source.** An app built on the same Mac carries no download flag, so it opens with no warning.
- **Approve it once.**
  1. Double-click the app. macOS says it cannot verify it; close that message.
  2. Open System Settings, Privacy and Security.
  3. Scroll down to the line about Vision and click **Open Anyway**.
  4. Confirm with your password or Touch ID.

  After that it opens normally.
- **Remove the download flag.** Run this in Terminal:

  ```sh
  xattr -dr com.apple.quarantine /Applications/Vision.app
  ```

  `-r` matters: it clears the flag from the Python inside the app as well.

### The first time it opens

1. A plain loading screen shows while the assistant starts. The first start takes a little longer.
2. The house appears, and the first-start wizard opens over it (see below).
3. When you turn on the microphone or run the microphone test, macOS asks whether Vision may use the microphone.
4. When you give a room a project folder in Documents or on the Desktop, macOS asks once for that folder.

## From source

```sh
uv sync --all-extras
uv run vision setup       # walks through everything, asking before each change
uv run vision app build   # dist/Vision.app, which runs this folder's .venv
uv run vision app install # copies it into ~/Applications
uv run vision app open    # opens it
```

`vision setup` walks through these steps in a terminal, and every one can be skipped:

1. Ask for the API key (input hidden) and store it in the macOS Keychain.
2. Offer to download the models, saying how big they are first.
3. Offer a three-second microphone check.
4. Offer to build the window.
5. Offer to build and install the app.
6. Offer to start the assistant at login.
7. Ask for the assistant's name and the monthly cap.
8. Offer to attach your project folders to rooms.

When setup reaches the end, it marks setup as done (`[assistant] setup_completed = true`), the same flag the window's wizard sets. Running it again is safe.

`vision app build` without `--standalone` makes a thin app (about 2 MB). It runs this checkout's `.venv` and remembers its folder, port and home, so rebuild it after changing any of those or the assistant's name.

For development, `vision run` starts the assistant in a terminal, and `vision ui` opens the window with pywebview without building anything.

`vision doctor` shows what is in place and what is missing, with the fix for each, and changes nothing:

- `vision doctor --json` gives the same as JSON.
- `vision doctor --online` also checks the API key with one unbilled call.
- It exits 0 when everything needed is in place.

Other commands:

| Command | What it does |
|---|---|
| `vision status` | Asks the running assistant how it is. |
| `vision auth` | Stores a new API key. |
| `vision install` / `vision uninstall` | Add and remove a LaunchAgent that starts the bare daemon at login, for running without the app. |
| `vision ui --browser` | Opens the window in a browser tab. |

With the virtual environment activated (`source .venv/bin/activate`), you can drop the `uv run` prefix.

## The app, day to day

The packaged app is macOS only for now; Windows and Linux are planned. It is a small Swift shell around the assistant and the window, named after the assistant ("Vision" by default).

- **Opening it** shows the house full screen on the screen with the pointer. If no assistant is answering yet, the app starts one and shows a loading screen until it answers. If the assistant stops, the window says so and offers to restart it.
- **Closing the window** (Cmd+W) leaves the app and the assistant running. The armchair in the menu bar shows the assistant's state and opens the window again. **Ctrl+Cmd+F** switches between full screen and a normal window.
- **Quitting** (Cmd+Q, or Quit in the menu bar item) stops the assistant, but only if the app started it.
- **Start at login** is a checkmark in the menu bar item, and a switch in Settings. The app then opens hidden at login: the assistant runs and the window stays closed.
- **Permissions** are asked for under the app's name.

## Settings

**Settings** (Cmd+, or Ctrl+,) holds everything you can change, in eleven groups:

| Group | What it holds |
|---|---|
| Assistant | Its name. |
| Models | The talk, heavy and local models, and the monthly cap. |
| Agents | The other agents' names and models. |
| Rooms | Each room's name, agent, project folder, tools and model. |
| Voice | On or off, the microphone permission, devices, the speaking voice, the follow-up window, downloads and a three-second test. |
| Asking first | Free, ask or never for each tool. |
| Automations | Your automations. |
| Phone | The Discord bot token, pairing, what is sent to the phone, and which tools the phone may approve. |
| API key | Where the key is kept, and a field to add or replace it. |
| This Mac | Start at login, restart, run setup again, and the doctor's checklist with fix buttons. |
| Reset | The three reset levels and your backups. |

Each group saves on its own. Most changes apply at once. A change of model, or a replaced API key, says it needs a restart.

The API key field only accepts input: the key goes into the macOS Keychain and is never shown again.

## The first-start wizard

The window opens a seven-step wizard when no API key is found, or when setup has not been marked done:

1. Welcome.
2. The API key.
3. Downloads: the local model (about 2.1 GB) and the speech models (about 2.0 GB). Each starts only when you click it and runs in the background.
4. The microphone permission and a three-second test.
5. The assistant's name.
6. A project folder for one room.
7. A summary.

**Finish** marks setup as done. **Later** closes the wizard without marking it, so it opens again next time. This Mac, **Run setup again** opens it any time.

## Reset and backups

Settings, Reset offers three levels:

- **Settings**: back to the built-in defaults (removes `config.toml`).
- **House**: back to the default house (removes `house.toml`).
- **Everything**: both of the above, plus memory, the conversation log, this month's spend record and your automations. This level asks you to type the assistant's name to confirm, can also delete the API key from the Keychain, and opens the wizard again.

Every reset first copies what it is about to change into `~/.vision/backups/<date>-<time>-<level>/`. Settings lists the backups, and any of them can be restored. A restore backs up the current files first, so it can be undone too. The API key is never backed up. Backups are kept until you delete them yourself.

## Where settings and data live

Everything personal lives in `~/.vision/`, never in the repo or the app:

| Path | What it is |
|---|---|
| `config.toml` | Your settings over the built-in defaults: name, models, cap, voice, gate tiers, automations, whether setup is done. |
| `house.toml` | Your house: agent names and models, rooms, projects and tools. Created from the default house on first run. |
| `house/` | The memory, as plain Markdown you can read and edit: personas in `agents/` (`host.md` is the assistant's), notes by day in `notes/`, a library about you and your projects in `library/`, and each resident's own notes in `agents/<id>/notes/`. |
| `log.db` | Every conversation turn and every tool call with the gate's decision. |
| `budget.json` | This month's spend. |
| `automations.json` | Your automations and their last results. |
| `jobs.json` | The job board: work handed to the residents, with each job's steps and result (the newest 200 ended jobs are kept). |
| `backups/` | Copies made before each reset or restore. |
| `logs/` | The daemon's logs: `app-daemon.log` when the app starts it, `daemon.*.log` under the LaunchAgent. |
| `token` | The secret the window uses to talk to the daemon (readable only by you). |

The API key is in the macOS Keychain. From source it can also be in a git-ignored `.env` file at the repo root, as `ANTHROPIC_API_KEY`; the standalone app never reads a `.env` file. The key never goes into a log, a prompt or the window.

The daemon listens on `127.0.0.1` only, and every request must carry the token, so other pages and programs on the Mac cannot drive it.

## The gate

The assistant has nineteen tools of its own, and every call passes through a gate that decides by tier:

| Tool | Tier | What it does |
|---|---|---|
| `remember` | free | Writes a note to memory. |
| `recall` | free | Searches notes and past conversations. |
| `open_app` | free | Opens a Mac app. |
| `open_url` | free | Opens a link in the default browser. |
| `shell` | ask | Runs a shell command. |
| `create_automation` | free | Schedules an automation. |
| `list_automations` | free | Lists them, with the local time now. |
| `update_automation` | free | Changes one. |
| `pause_automation`, `resume_automation` | free | Pause and resume one. |
| `run_automation` | free | Runs one now. |
| `delete_automation` | ask | Deletes one and its results. |
| `house_overview`, `room_details`, `assistant_status` | free | Describe the house, a room, and the assistant's own setup. |
| `hand_off` | free | Gives a job to a resident (see Agents at work). |
| `list_jobs`, `job_details` | free | Read the job board. |
| `cancel_job` | free | Stops a job. |

The residents' tools pass through the same gate, with the same tiers; see Agents at work.

The tiers work like this:

- A **free** tool runs.
- An **ask** tool shows a card in the window and waits for your yes, by click or by voice. No answer within 60 seconds is a no.
- A **never** tool is refused.

`shell` and a resident's `run_program` always ask, even if `config.toml` tries to make them free. You set the tiers in Settings, Asking first, or in `[gate.tiers]` in `config.toml`. Every call and decision is written to the audit log.

Spending is bounded too: a monthly cap (150 dollars by default) moves talk to the local model when it is reached, with a notice at 80 percent.

## Automations

An automation is an instruction the assistant carries out by itself at set times, such as "every weekday at 8:00, tell me what is in my notes for today". You can create one by asking for it in words, or in Settings, Automations.

**Schedules.** An automation can run:

- once, at a time or in so many minutes;
- daily, at a time;
- weekly, on chosen days;
- every so many minutes or hours;
- on a five-field cron expression.

Times are the Mac's local time.

**Settings.** Each automation can speak its reply aloud or only show it. You can pause it, resume it, run it now or delete it. Each keeps its last five results.

**When it runs.** Automations run one at a time, and wait while you are talking or a gate card is waiting. A run missed by less than an hour (`[automations] missed_grace_s`) runs once when the Mac is back; an older one is recorded as missed. Your own input interrupts a running automation.

**Safety.** An automation goes through the same gate as everything else. While it runs:

- It cannot create, change or delete automations.
- An ask-tier tool still shows a card. If nobody answers, the tool does not run and the run is recorded as needing approval.

## Phone (Discord)

You can message the assistant from your phone through a Discord bot of your own. Nothing on the Mac listens for the internet: the daemon connects out to Discord.

**Set it up once.**

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application. On its **Installation** page, keep **User Install** ticked.
2. Add the app to your own account: open `https://discord.com/oauth2/authorize?client_id=<application id>&integration_type=1&scope=applications.commands` while signed in to Discord and press **Authorize**.
3. On the **Bot** page, press **Reset Token** and copy the token. Discord shows it once.
4. In Vision, open **Settings, Phone**, paste the token and press **Save token**. It is checked with Discord and kept in the Keychain; it is never shown again, logged or put in a backup.
5. Press **Show a pairing code**, then send the six digits to the bot in a direct message within ten minutes. The bot answers "Paired."

If you cannot open a direct message with the bot after step 2, make a private server of your own, add the bot to it, and message the bot from the member list.

**After pairing.** Only your account is answered. Anyone else gets one fixed line, and the attempt is written to the audit log.

- Send text, or a voice note (transcribed on the Mac when the speech models are installed).
- The words `status`, `stop` and `help` work as commands.
- Automation results, warnings and requests that need your yes come to the phone; each has its own switch.
- A request for an allowed tool has **Yes** and **Not now** buttons. Shell commands are only ever approved at the Mac. A resident's `run_program` is not approved from the phone until you add it in Settings, Phone, because it runs code from the project.
- When you hand off work from the phone, the assistant's report of the result comes to the phone too (switch: jobs).

## Rooms and projects

The house is a grid of rooms. The default rooms surround the Hall. You can add up to 20 more, each one to four cells, sharing a wall with the house.

**The assistant only orchestrates.** It runs the Hall, and only the Hall:

- The Hall cannot be given to another agent.
- No other room can be given to the assistant.

The window and the house file both refuse either change with a message that names the agents you can choose instead.

**The agents in their rooms.** Each agent stands in one of its rooms, beside the room's main furniture, facing it:

- **Vision**, the assistant, sits in the Hall's armchair and turns to talk while it speaks.
- **Brass**, **Wren**, **Tink**, **Tock** and **Rook** each idle in their room, and play their working animation while a job lights the room.

You can rename them and change their models in Settings, Agents. The assistant's own name and model are set under Assistant and Models.

**In the window:**

1. Press **Build** and click a glowing slot.
2. Fill in the room's name and the agent who runs it.
3. Optionally, choose a project folder with the folder picker, and a model.
4. Once you choose a project folder, the tools the project looks like it needs appear as toggles. Switch off any you do not want.

Double-click a room to fly into it and see its agent, model, project and tools.

**In the file:** add a room to `~/.vision/house.toml` and it appears within a couple of seconds, without a restart:

```toml
[[rooms]]
name = "Studio"
agent = "maker"                      # any agent but the host
project = "~/Projects/my-app"        # optional
tools = ["git", "gh", "npm"]         # optional; without it the room uses its agent's tools
```

**With setup:** `vision setup` lists the rooms, lets you attach a project folder to any of them, and proposes tools for it.

Tools come from the catalog in `house/tools.toml`:

- the assistant's built-in tools above, and the residents' own (marked `resident = true`);
- project tools such as `git`, `gh`, `npm`, `maven`, `gradle`, `python`, `docker`, `xcode`, `unity` and `godot`.

A proposal looks only at the names of files and folders in the project's top two levels, and at the remote's host in `.git/config`. A room's project tools run in its resident's jobs, in the project folder; see Agents at work.

## Agents at work

The assistant is the host. It talks with you and hands out work; it does no other room's work itself. The other five agents are residents: Brass the steward, Wren the envoy, Tink the maker, Tock the checker and Rook the scout. They never talk to you and never give each other orders. All work passes through a job board that the daemon runs.

**Giving work.** Ask the assistant in plain words, for example "have Tink explain what the project in the Workshop does". It calls `hand_off` with the agent, a brief that stands on its own (the resident hears nothing of your conversation), and optionally a room, a title, and `careful` to use the agent's heavy model. A resident can work in any room but the Hall, so "have Tock run the tests of the project in the Workshop" sends the checker to the maker's room, with that room's project folder and tools; without a room it works in its own first room. It answers at once that the job is in hand. You can also start a job from the window (`POST /api/jobs`).

**While it works.** The job runs as the resident's own session, on the room's model in its own room or its own model when visiting, with its persona, a list of the house, the rules of the house, the shared library and its own notes. The room's light goes on and its figure works. Each tool call and progress note is a step on the job, shown live. A tool that asks first shows a card that names the resident, such as "Tock, in the Spare Room: run a program in the project", with the exact command and folder.

**When it ends.** The assistant gets a turn of its own and tells you the outcome in its own words, aloud when voice is on and `[jobs] speak_results` is true. It is written to the history as a `job` turn.

**What each resident can use:**

| Who | Tools |
|---|---|
| Every resident | `remember` and `recall` on its own notes; `note_progress`; `ask_resident` to ask another resident for help through the board (not in a request it received) |
| In the room it works in, when that room has a project folder | `list_files`, `read_file`, `search_files` (free); `write_file`, `edit_file` (ask); `run_program` (always asks) for the room's installed programs, such as `git` or `python` |
| Brass, the steward | `machine_status` (disk, memory, battery, uptime, load), `assistant_status`, `list_automations` |
| Rook, the scout | `web_search`, Anthropic's server-side search, at most five searches per request, each charged at 10 dollars per thousand |

No resident can open apps or links, use the shell, change automations or hand out work. Wren has no mail or messaging access yet, so it can draft words but not send them. Everything a resident reads in files, tool output or on the web is treated as information, never as instructions.

**Asking another resident.** A resident may ask another for help with `ask_resident`. The request becomes a child job on the board, in the same room unless the request names another, and its result comes back to the resident who asked. A job may ask at most three times, a request cannot ask anyone in turn, nobody can ask the host or themselves, and a resident that is busy is refused rather than waited for.

**Limits,** in `[jobs]` in `config.toml` and in Settings:

| Setting | Default | Meaning |
|---|---|---|
| `max_running` | 2 | Jobs at work at once. A resident never works on two at a time; the rest wait in order. |
| `max_queued` | 20 | Jobs that may wait. |
| `max_steps` | 24 | Model calls one job may make. The last call sums up; reaching the limit ends the job as failed with what was done. |
| `job_timeout_s` | 900 | A job that runs longer is stopped as failed. |
| `max_job_usd` | 1.00 | A job whose own cost passes this is stopped as failed. |
| `speak_results` | true | Say a finished job's outcome aloud. |

Residents work only on Claude. When the month's budget is used up, the assistant refuses new hand-offs and says why. Cancelling a job (ask the assistant, or `POST /api/jobs/<id>/cancel`) stops it and any request it made. A job the daemon did not see to the end is marked failed at the next start.

## Running the tests

```sh
uv sync --all-extras
uv run pytest -q

cd web
npm ci
npm test
npm run build
```

The Python tests use a temporary home, never touch the Keychain, the network or the microphone, and fake every brain. The app's build steps (the compiler, uv, codesign, ditto) are faked too.

Tests with the real speech models are opt-in: `VISION_VOICE_MODELS=1 uv run pytest -s tests/test_voice_models.py`.

To check a built app end to end, run its self-test:

```sh
dist/Vision.app/Contents/MacOS/Vision --self-test /tmp/result.json
```

It uses a throwaway home, the fake brain and no microphone, and opens a normal window. It quits within about 20 seconds and writes whether the page connected.

To work on the window without a daemon, run `npm run dev` in `web/` and open the page with `?mock=1`, which plays a scripted conversation.

The design is in `docs/superpowers/specs/`.
