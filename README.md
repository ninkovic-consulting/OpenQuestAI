# OpenQuestAI

OpenQuestAI is a personal assistant that runs all the time on one Mac, for one person: a Python daemon is its mind, and a 3D house seen from above, with the roof off, is its face. You talk to the assistant, called Vision by default, by voice or by typing, and it answers aloud, remembers what you tell it, and asks before it does anything risky.

The command is `vision`. No licence has been chosen yet.

## What it needs

- **macOS on Apple Silicon.**
- **[uv](https://docs.astral.sh/uv/)**, which brings Python 3.12.
- **An Anthropic API key**, from console.anthropic.com.

Everything else is optional:

| Part | What it gives you |
|---|---|
| The local model (about 2.3 GB) | Answers when Claude is offline or the monthly cap is reached. |
| The speech models (about 2 GB) and a microphone | Talking by voice. Without them, typing works the same way. |
| Node.js | Building the window. |
| The GitHub CLI (`gh`), signed in | GitHub work in project rooms, once the other agents wake up. |
| Tailscale | Reaching the house from a phone, in a later version. |

## Quick start

```sh
uv sync --all-extras
uv run vision setup     # walks through everything, asking before each change
uv run vision run       # starts the assistant in this terminal
uv run vision ui        # opens the window, in another terminal
```

`vision setup` asks for the API key (input hidden) and stores it in the macOS Keychain, offers to download the models (saying how big they are first), to run a three-second microphone check, to build the window, to start the assistant at login, and to attach your project folders to rooms. Every step can be skipped, and running it again is safe.

`vision doctor` shows what is in place and what is missing, with the fix for each, and changes nothing. `vision doctor --json` gives the same as JSON, and `vision doctor --online` also checks the API key with one unbilled call. It exits 0 when everything needed is in place.

Other commands: `vision status` asks the running assistant how it is, `vision auth` stores a new API key, `vision install` and `vision uninstall` add and remove the LaunchAgent that starts it at login, and `vision ui --browser` opens the window in a browser tab. With the virtual environment activated (`source .venv/bin/activate`) you can drop the `uv run` prefix.

## Where settings and data live

Everything personal lives in `~/.vision/`, never in the repo:

| Path | What it is |
|---|---|
| `config.toml` | Your settings over the built-in defaults: the assistant's name, models, the monthly cap, voice devices, gate tiers. |
| `house.toml` | Your house: agent names, rooms, projects and tools. Created from `house/default.toml` on first run. |
| `house/` | The memory, as plain Markdown you can read and edit: the persona, notes, and a library about you and your projects. |
| `log.db` | Every conversation turn and every tool call with the gate's decision. |
| `logs/` | The daemon's logs when it runs at login. |
| `token` | The secret the window uses to talk to the daemon (readable only by you). |

The API key is in the macOS Keychain, or in a git-ignored `.env` file at the repo root as `ANTHROPIC_API_KEY`. It never goes into a log, a prompt or the window.

The daemon listens on `127.0.0.1` only, and every request must carry the token, so other pages and programs on the Mac cannot drive it.

## The gate

The assistant has five tools, and every call passes through a gate that decides by tier:

| Tool | Tier | What it does |
|---|---|---|
| `remember` | free | Writes a note to memory. |
| `recall` | free | Searches notes and past conversations. |
| `open_app` | free | Opens a Mac app. |
| `open_url` | free | Opens a link in the default browser. |
| `shell` | ask | Runs a shell command. |

A **free** tool runs. An **ask** tool shows a card in the window and waits for your yes, by click or by voice; no answer within 60 seconds is a no. A **never** tool is refused. It will never run a shell command without asking: `shell` always asks, even if `config.toml` tries to make it free. Tiers are set in `[gate.tiers]` in `config.toml`, and every call and decision is written to the audit log.

Spending is bounded too: a monthly cap (150 dollars by default) moves talk to the local model when it is reached, with a notice at 80 percent.

## Rooms and projects

The house is a grid of rooms. The default rooms surround the Hall, where the assistant sits, and you can add up to 20 more, each one to four cells, sharing a wall with the house.

**In the window:** press **Build**, click a glowing slot, and fill in the name, the agent who runs the room, and optionally a project folder and a model. Once you enter a project folder, the tools the project looks like it needs appear as toggles; switch off any you do not want. Double-click a room to fly into it and see its agent, model, project and tools.

**In the file:** add a room to `~/.vision/house.toml` and it appears within a couple of seconds, without a restart:

```toml
[[rooms]]
name = "Studio"
agent = "maker"                      # one of the agents in the file
project = "~/Projects/my-app"        # optional
tools = ["git", "gh", "npm"]         # optional; without it the room uses its agent's tools
```

**With setup:** `vision setup` lists the rooms, lets you attach a project folder to any of them, and proposes tools for it.

Tools come from the catalog in `house/tools.toml`: the five built-in tools above, and project tools such as `git`, `gh`, `npm`, `maven`, `gradle`, `python`, `docker`, `xcode`, `unity` and `godot`. A proposal looks only at the names of files and folders in the project's top two levels and at the remote's host in `.git/config`. In this version, project tools are stored and shown for each room, but only the assistant's five built-in tools run; project tools start working when the other agents wake up in the next version.

## Running the tests

```sh
uv sync --all-extras
uv run pytest -q

cd web
npm ci
npm test
npm run build
```

The Python tests use a temporary home, never touch the Keychain, the network or the microphone, and fake every brain. Tests with the real speech models are opt-in: `VISION_VOICE_MODELS=1 uv run pytest -s tests/test_voice_models.py`.

To work on the window without a daemon, run `npm run dev` in `web/` and open the page with `?mock=1`, which plays a scripted conversation.

The design is in `docs/superpowers/specs/`.
