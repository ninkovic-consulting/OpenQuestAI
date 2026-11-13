# OpenQuestAI

[![Release build](https://github.com/ninkovic-consulting/OpenQuestAI/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/ninkovic-consulting/OpenQuestAI/actions/workflows/release.yml)

OpenQuestAI is a personal assistant that runs all the time on one Mac, for one person: a Python daemon is its mind, and a 3D house seen from above, with the roof off, is its face. You talk to the assistant, called Vision by default, by voice or by typing, and it answers aloud, remembers what you tell it, runs automations you set up, and asks before it does anything risky.

The command is `vision`.

## Download

The latest build of the Mac app is on the [Releases page](https://github.com/ninkovic-consulting/OpenQuestAI/releases). Every merge to `main` publishes a new one, marked as a beta; take the newest. It needs a Mac with Apple Silicon and macOS 14 or later.

The app is signed ad hoc, not with an Apple Developer ID, so macOS blocks it the first time. To open it:

1. Unzip the download, move `Vision.app` into Applications and double-click it. macOS says it cannot verify the app; close that message.
2. Open System Settings, Privacy and Security, scroll down to the line about Vision and click **Open Anyway**.
3. Confirm with your password or Touch ID. After that it opens normally.

The details, and a Terminal command that does the same, are under "Opening an app not signed with a Developer ID" below. How the builds are made is in `docs/releasing.md`.

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
4. When you give a room a project folder in Documents or on the Desktop, macOS asks once for each such folder.

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

The packaged app is macOS only for now; Windows and Linux are planned. It is a small Swift shell around the assistant, the window and a small floating widget, named after the assistant ("Vision" by default).

- **Opening it** shows the house full screen on the screen with the pointer. If no assistant is answering yet, the app starts one and shows a loading screen until it answers. If the assistant stops, the window says so and offers to restart it.
- **Closing the window** (Cmd+W) leaves the app, the widget and the assistant running. The armchair in the menu bar shows the assistant's state, opens the house again (**Open the house**) and shows or hides the widget. **Ctrl+Cmd+F** switches between full screen and a normal window.
- **The widget** is a small window that floats above every app, on every desktop and over full-screen apps, without taking the keyboard from the app you are in until you click it. It shows the assistant's name and state, the latest exchange, any request waiting for your yes (the oldest, with Yes, Not now and how many more wait), a message field and hold to talk. **House** opens the house; **Hide** hides it, which never stops the assistant. Drag it by its name to put it anywhere; it remembers its place for each arrangement of screens.
- **Two shortcuts** work in any app, with no Accessibility permission: **Option+Space** brings up the widget with the cursor in its field (press it again to send it away), and **Control+Option+Space** held is push to talk (let go to stop). Choose others from a short list, or turn them off, in **Settings, This Mac, Widget and shortcuts**; if one is taken by another app or by macOS, that block says so. The same block turns the widget on or off and sets what the app shows when it opens: the house, or only the widget.
- **Quitting** (the **Quit** button in the window's left panel or in **Settings, This Mac**, Cmd+Q, or Quit in the menu bar item) stops the assistant, but only if the app started it. The button asks first.
- **Start at login** is a checkmark in the menu bar item, and a switch in Settings. The app then opens hidden at login: the assistant runs and the window stays closed; with the widget on, the widget shows.
- **Permissions** are asked for under the app's name.

## Settings

**Settings** (Cmd+, or Ctrl+,) holds everything you can change, in twelve groups:

| Group | What it holds |
|---|---|
| Assistant | Its name, and About you: what to call you, your business, and anything else to keep in mind. |
| Library | Your documents: add files or pasted text, read, rename and remove them. |
| Models | The talk and heavy models with their thinking effort, the monthly cap, offline mode, and the local model: the catalog marked for this Mac, downloads, deleting, or a local server. |
| Agents | The other agents' names, models and thinking effort. |
| Rooms | Each room's name, agent, project folders, tools and model. |
| Voice | On or off, the microphone permission, devices (listed fresh each time, with Refresh), the speaking voice with a test sentence, the follow-up window, downloads and a three-second test. A chosen device that is not connected shows as such, and the system default is used with a notice. A microphone that opens but sends only silence is named, with the likely causes first (muted, asleep, covered, a closed laptop lid) and Try again. |
| Asking first | Free, ask or never for each tool. |
| Automations | Your automations. |
| Phone | The Discord bot token, pairing, what is sent to the phone (always, when away or never, per kind), the away time with whether you are here now, and which tools the phone may approve. |
| API key | Where the key is kept, and a field to add or replace it. |
| This Mac | Start at login, the widget and its two shortcuts (in the Mac app only), restart, run setup again, and the doctor's checklist with fix buttons. |
| Reset | The three reset levels and your backups. |

Each group saves on its own. Most changes apply at once, offline mode and the local model among them. A change of Claude model, or a replaced API key, says it needs a restart.

**Thinking effort.** Each Claude model thinks before it answers, and its effort (`low`, `medium`, `high`, `xhigh`, `max`) sets how much. A higher level answers more carefully, but more slowly and with more tokens, so it costs more. The host talks at `low` and thinks things through at `high` (`[brain] talk_effort` and `heavy_effort`); a resident works at `medium` and at `high` on a careful job (`effort` and `heavy_effort` on the agent in the house file). Not every model takes every level: Claude Opus 4.6 and Sonnet 4.6 have no `xhigh`, and Haiku 4.5 takes none, so Settings offers only the levels the chosen model takes and refuses the others with the list it does take. Local models have no effort setting and ignore it.

The API key field only accepts input: the key goes into the macOS Keychain and is never shown again.

## The first-start wizard

The window opens an eight-step wizard when no API key is found, or when setup has not been marked done:

1. Welcome.
2. The API key.
3. Downloads: the local model (about 2.1 GB) and the speech models (about 2.0 GB). Each starts only when you click it and runs in the background. Nothing downloads by itself: with voice on and no speech models, voice stays off with a notice naming what is missing and Settings, Voice offers the download (voice starts when it finishes). Speech models are never deleted by the app; no reset touches them.
4. The microphone permission and a three-second test.
5. The assistant's name.
6. About you: what it should call you, what business you run, and anything else it should know. All optional; `vision setup` in a terminal asks the same.
7. Project folders for one room.
8. A summary.

**Finish** marks setup as done. **Later** closes the wizard without marking it, so it opens again next time. This Mac, **Run setup again** opens it any time.

## Reset and backups

Settings, Reset offers three levels:

- **Settings**: back to the built-in defaults (removes `config.toml`).
- **House**: back to the default house (removes `house.toml`).
- **Everything**: both of the above, plus memory (with what it knows about you and your library), the conversation log, this month's spend record and your automations. This level asks you to type the assistant's name to confirm, can also delete the API key from the Keychain, and opens the wizard again.

Every reset first copies what it is about to change into `~/.vision/backups/<date>-<time>-<level>/`. Settings lists the backups, and any of them can be restored. A restore backs up the current files first, so it can be undone too. The API key is never backed up. Backups are kept until you delete them yourself.

## Where settings and data live

Everything personal lives in `~/.vision/`, never in the repo or the app:

| Path | What it is |
|---|---|
| `config.toml` | Your settings over the built-in defaults: name, models, cap, voice, gate tiers, automations, whether setup is done. |
| `house.toml` | Your house: agent names and models, rooms, project folders and tools. Created from the default house on first run. |
| `house/` | The memory, as plain Markdown you can read and edit: personas in `agents/` (`host.md` is the assistant's), notes by day in `notes/`, your documents in `library/`, what it knows about you in `owner.md`, and each resident's own notes in `agents/<id>/notes/`. |
| `log.db` | Every conversation turn and every tool call with the gate's decision. |
| `budget.json` | This month's spend. |
| `automations.json` | Your automations and their last results. |
| `jobs.json` | The job board: work handed to the residents, with each job's steps and result (the newest 200 ended jobs are kept). |
| `backups/` | Copies made before each reset or restore. |
| `logs/` | The daemon's logs: `app-daemon.log` when the app starts it, `daemon.*.log` under the LaunchAgent. |
| `token` | The secret the window uses to talk to the daemon (readable only by you). |

The API key is in the macOS Keychain. From source it can also be in a git-ignored `.env` file at the repo root, as `ANTHROPIC_API_KEY`; the standalone app never reads a `.env` file. The key never goes into a log, a prompt or the window.

The daemon listens on `127.0.0.1` only, and every request must carry the token, so other pages and programs on the Mac cannot drive it.

## What the assistant knows about you

**Your profile.** Three things, all optional: what to call you, your business (its name and what it does, in your own words), and anything else it should always keep in mind. You give them in the wizard's About you step, in `vision setup`, or in Settings, Assistant; or just tell the assistant ("call me Dee from now on", "we've started a catering line"), and it saves the change itself with its `update_profile` tool. It addresses you by that name from the next thing you say. The profile is a short Markdown file, `~/.vision/house/owner.md`, which you can also edit by hand. It goes into every conversation, and the other agents get it with every job.

**Your documents.** The library holds what the assistant and the other agents should be able to look up: a price list, your terms, a handbook, notes about a project. Add them in Settings, Library, by choosing files or dropping them on the group (text, Markdown, PDF and Word `.docx`, up to 20 MB and 400,000 characters of text each), or paste text with a title. You can also ask the assistant to save something you dictate as a document, or write Markdown files into the folder yourself. A scanned PDF has no text in it and is refused with a line that says so.

- **Where they are.** `~/.vision/house/library/`: each document's text as `<name>.md`, the file you added as it was in `originals/`, titles and kinds in `index.json`, and `.search.db`, the search index, rebuilt from the files whenever they change.
- **What is sent to the model.** Short documents (up to about 2,000 characters) are in every conversation in full. Every other one is only listed, with its title, size and a one-line gist; its text goes to the model only when a conversation needs it, when the assistant reads a part of it or searches the library (`read_document`, `search_documents`). The same holds for the other agents at work. What a document says is treated as information, never as an instruction.
- **Removing them.** In Settings, Library, Remove deletes a document's text and its original after you confirm; when you ask the assistant to remove one, it asks first. Deleting the files from the folder works too. Reset, Everything clears the profile and the library with the rest of the memory, after copying them into a backup.

## The gate

The assistant has nineteen tools of its own, and every call passes through a gate that decides by tier:

| Tool | Tier | What it does |
|---|---|---|
| `remember` | free | Writes a note to memory. |
| `recall` | free | Searches notes and past conversations. |
| `open_app` | free | Opens a Mac app. |
| `open_url` | free | Opens a link in the default browser on the Mac's screen, for you to look at; the assistant cannot see the page. |
| `shell` | ask | Runs a shell command. Can be made free, for what you type or say at the Mac only. |
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
| `send_to_phone` | free | Messages your paired phone now, when you ask or an automation should ping you. The host's only. |

The residents' tools pass through the same gate, with the same tiers; see Agents at work.

The tiers work like this:

- A **free** tool runs.
- An **ask** tool shows a card in the window and waits for your yes, by click or by voice. No answer within 60 seconds is a no.
- A **never** tool is refused.

A resident's `run_program` always asks, even if `config.toml` tries to make it free. `shell` asks by default. You can make it free in Settings, Asking first (the window asks you to confirm, because a free shell command runs at once, without a card, and can do anything on the Mac). Free holds only for turns you typed or said at the Mac: during an automation's run, a job report or a message from your phone, `shell` still asks first, at the Mac, since nobody may be watching and those turns can carry words you did not write. It is never approved from the phone. You set the tiers in Settings, Asking first, or in `[gate.tiers]` in `config.toml`. Every call and decision, a free shell command's included, is written to the audit log.

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

The full guide, with every step, how to use it and what to do when something goes wrong, is in [docs/discord.md](docs/discord.md). In short:

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
- What you type on the phone is answered on the phone and kept in the app; what you type or say at the Mac is answered at the Mac, never on the phone; anything the assistant does by itself reaches both, whether you are at the Mac or not: automation results, every job result, warnings and errors, requests that need your yes, and messages it sends on purpose (`send_to_phone`, for "send that to my phone" or an automation that should ping you).
- For less on the phone, each of those kinds can be set to **When away** or **Never** in Settings, Phone (default **Always**); switches from an older `phone.json` carry over (on is always, off is never). Away means no keyboard, mouse or voice at the Mac for `[presence] away_after_s` (default 300 seconds), a locked screen or a sleeping display, read through CoreGraphics with no macOS permission; if the Mac will not say, you count as here. It matters only for a kind set to When away.
- Each message is sent once; one that does not arrive is tried again a few times, then dropped with a note in the app. In the window, what came while you were not looking sits under **While you were away** until you have seen it.
- A request for an allowed tool has **Yes** and **Not now** buttons. Shell commands are only ever approved at the Mac. A resident's `run_program` is not approved from the phone until you add it in Settings, Phone, because it runs code from the project.
- Work handed off from the phone reports back to the phone unless job results are set to never.

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
3. Optionally, choose one or more project folders with the folder picker, and a model.
4. Once you choose project folders, the tools they look like they need appear as toggles. Switch off any you do not want.

Double-click a room to fly into it and see its agent, model, project folders and tools. You can add more folders to a room later, in Settings, Rooms.

**Project folders.** A room can have up to eight project folders, so one room can hold a project made of several repositories, such as an app and its API. Each is a full path (starting with `/` or `~`). A folder cannot be the disk, your home folder or a folder above it, cannot be listed twice, and cannot sit inside another folder of the same room. A folder you add must exist; one that goes missing later (a disconnected disk, say) stays listed, and a job in the room says it is not there and works in the others.

Residents know each folder by a short name, its own name: `~/Projects/shop` is `shop`. Two folders with the same name become `app` and `app-2`. Every path a resident uses starts with that name, such as `shop/src/app.py`, even when the room has only one folder, so what a resident wrote down still points to the same file after you add another folder.

**In the file:** add a room to `~/.vision/house.toml` and it appears within a couple of seconds, without a restart:

```toml
[[rooms]]
name = "Studio"
agent = "maker"                      # any agent but the host
folders = ["~/Projects/my-app", "~/Projects/my-app-api"]   # optional
tools = ["git", "gh", "npm"]         # optional; without it the room uses its agent's tools
```

**With setup:** `vision setup` lists the rooms, lets you add a project folder to any of them (one at a time, added to the room's list), and proposes tools for it.

A room in the file names its folders with `folders`; there is no `project` setting. A file that uses `project` is not applied: the default house is used until you fix it, and a notice says to write `folders = [...]` instead.

Tools come from the catalog in `house/tools.toml`:

- the assistant's built-in tools above, and the residents' own (marked `resident = true`);
- project tools such as `git`, `gh`, `npm`, `maven`, `gradle`, `python`, `docker`, `xcode`, `unity` and `godot`.

A proposal looks only at the names of files and folders in a folder's top two levels, and at the remote's host in `.git/config`. A room's project tools run in its resident's jobs, in the room's project folders; see Agents at work.

## Agents at work

The assistant is the host. It talks with you and hands out work; it does no other room's work itself. The other five agents are residents: Brass the steward, Wren the envoy, Tink the maker, Tock the checker and Rook the scout. They never talk to you and never give each other orders. All work passes through a job board that the daemon runs.

**Giving work.** Ask the assistant in plain words, for example "have Tink explain what the project in the Workshop does". It calls `hand_off` with the agent, a brief that stands on its own (the resident hears nothing of your conversation), and optionally a room, a title, and `careful` to use the agent's heavy model. A resident can work in any room but the Hall, so "have Tock run the tests of the project in the Workshop" sends the checker to the maker's room, with that room's project folders and tools; without a room it works in its own first room. It answers at once that the job is in hand. You can also start a job from the window (`POST /api/jobs`).

**While it works.** The job runs as the resident's own session, on the room's model in its own room or its own model when visiting, with its persona, a list of the house, the rules of the house, your profile and library, and its own notes; it can read and search your documents. The room's light goes on and its figure works. Each tool call and progress note is a step on the job, shown live. A tool that asks first shows a card that names the resident, such as "Tock, in the Spare Room: run a program in the project", with the exact command and the folder it runs in.

**When it ends.** The assistant gets a turn of its own and tells you the outcome in its own words, aloud when voice is on and `[jobs] speak_results` is true. It is written to the history as a `job` turn, and goes to the phone by the choice for job results (Settings, Phone).

**What each resident can use:**

| Who | Tools |
|---|---|
| Every resident | `remember` and `recall` on its own notes; `note_progress`; `ask_resident` to ask another resident for help through the board (not in a request it received) |
| In the room it works in, when that room has a project folder | `list_files`, `read_file`, `search_files` (free); `write_file`, `edit_file` (ask); `run_program` (always asks) for the room's installed programs, such as `git` or `python`, in the folder it names (the room's first folder by default) |
| Brass, the steward | `machine_status` (disk, memory, battery, uptime, load), `assistant_status`, `list_automations` |
| Rook, the scout | `web_search`, Anthropic's server-side search, at most five searches per request, each charged at 10 dollars per thousand; `web_fetch`, Anthropic's server-side page fetch, at most five pages per request, costing only the tokens of what it reads. Both are free under Asking first by default and can be set to ask or never. |

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

**Web work goes to the scout by itself.** When you ask the assistant to look at, check, read or research a website, a link or anything that needs the web, it hands the work to Rook at once and tells you it is under way; it does not ask first. Rook loads the page itself, each page is a step on the job ("Fetched a page: https://example.com"), and a page that could not be loaded is named with the reason. Tests and reviews go to Tock and code to Tink the same way. The assistant cannot see web pages itself; `open_url` only puts a page on the Mac's screen.

Residents work on Claude, and on the local model in offline mode (below). When the month's budget is used up or no API key is stored, a job runs on the local model if it is downloaded and can use tools; otherwise the assistant refuses new hand-offs and says why. Cancelling a job (ask the assistant, or `POST /api/jobs/<id>/cancel`) stops it and any request it made. A job the daemon did not see to the end is marked failed at the next start.

## Local models and offline mode

The assistant can run on a model on this Mac instead of Claude. It does so by itself when Claude cannot be reached, the key is missing or the month's budget is used up, and always when you turn on **offline mode** in Settings, under Models (`[brain] offline` in `config.toml`).

**Which model for which Mac.** Settings lists a catalog of MLX models (`house/local_models.toml`, sizes taken from Hugging Face on 2026-11-13) and marks each for this Mac's memory: fits comfortably, fits tightly, or too big, with one recommended.

| Mac memory | Recommended | Size on disk |
|---|---|---|
| 8 GB | Qwen3.5 4B (the default Qwen3 4B Instruct also fits) | 3.1 GB |
| 16 GB | Qwen3.5 9B, the smallest that uses tools well | 6.0 GB |
| 32 GB | Qwen3.8 27B (or Gemma 4 31B; Qwen3 Coder 30B for code) | 16.1 GB |
| 36 to 96 GB | Qwen3.6 35B A3B, smart and fast | 20.4 GB |
| 128 GB | Qwen3.5 122B A10B | 69.6 GB |

A local model is downloaded, kept and removed only by your choice: only when you click Download (or answer yes in the first-start wizard or `vision setup`), with its size and progress, and only Delete removes one (not the model offline mode is using). The recommendation is a suggestion and changes nothing by itself, a fresh install downloads nothing, and resets and restores never touch downloaded models. If the assistant needs the local model (offline mode, or Claude cannot be used) and none is on this Mac, it fetches nothing: the answer, and a notice, say that no local model is downloaded and to choose one in Settings, under Models. You can type any other Hugging Face repo in MLX format, or use a local server that speaks the OpenAI format (LM Studio, Ollama and the like): choose the server backend, give its address and the model's name, and Test lists the server's models. A changed model is used from the next answer on.

**What works offline.** Nothing is sent to Anthropic and nothing is charged. The assistant answers on the local model, and with a model that can use tools it remembers and recalls, opens apps and links, runs shell commands after your yes, and hands work to the residents, who do it on the same model through the same job board, gate, project tools and audit. One answer is generated at a time: the assistant's turns go first, and the residents' steps wait their turn (`max_running` still says how many jobs may be open at once). A job already running when you switch finishes where it started, except that a job on Claude stops before its next call when offline mode comes on.

**What does not.** Web search and loading web pages need Anthropic, so the scout cannot reach the web offline. A model whose chat template has no tool format (gpt-oss and Llama 3.3 with the mlx-lm installed here) can only talk: the assistant says what it cannot do, and hand-offs are refused with the reason. Offline mode cannot be turned on until the chosen model is downloaded (or the server answers with it). Small models call tools less reliably: the 4B models are offered a short list of tools and a short prompt, and a call they write wrongly is answered with an error and never run on a guess. For offline work with tools, a 9B model or larger is the better choice.

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

It uses a throwaway home, the fake brain and no microphone, and opens a normal window and the widget. It quits within about 30 seconds and writes whether the house and the widget connected, whether the widget showed and hid, and whether each shortcut registered (or why not). To test a build without touching `dist/`, build it elsewhere with `vision app build --out <folder>`.

To work on the window without a daemon, run `npm run dev` in `web/` and open the page with `?mock=1`, which plays a scripted conversation; the widget is `widget.html?mock=1`.

The design is in `docs/superpowers/specs/`.

## Licence

MIT, see `LICENSE`. The 3D models, textures and icon under `assets/` were generated by the project's owner and are published under the same licence; see `assets/NOTICE.md`.
