"""`vision setup`: walk the checklist and fix what can be fixed, one yes at a time.

Every step can be skipped, and a step that is already done says so and moves
on, so running it twice is safe. It ends by printing the doctor's checklist.
Plain `input` and `getpass`, so it works in any terminal.
"""

from __future__ import annotations

import asyncio
import getpass
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from vision.core.bus import Bus
from vision.core.config import Config, load_config
from vision.house import GridHouse, HouseError, propose_tools
from vision.house.tools import tool_refs
from vision.setup import checks, doctor
from vision.setup.config_file import update_config
from vision.setup.hf_cache import gigabytes
from vision.setup.system import System
from vision.voice.settings import VoiceSettings

LOCAL_ESTIMATE = "about 2.3 GB"
TOOLS_NOTE = (
    "Project tools are stored and shown now; they start working when the other agents "
    "wake up in the next slice. Today only {name}'s five built-in tools run."
)


class Prompter(Protocol):
    def say(self, text: str = "") -> None: ...
    def ask(self, prompt: str) -> str: ...
    def secret(self, prompt: str) -> str: ...


class Terminal:
    def say(self, text: str = "") -> None:
        print(text)

    def ask(self, prompt: str) -> str:
        return input(prompt)

    def secret(self, prompt: str) -> str:
        return getpass.getpass(prompt)


class Setup:
    def __init__(self, config: Config, system: System, io: Prompter) -> None:
        self.config = config
        self.system = system
        self.io = io

    # ------------------------------------------------------------ prompts

    def answer(self, prompt: str) -> str:
        """The reply, stripped; empty when input has ended."""
        try:
            return self.io.ask(prompt).strip()
        except EOFError:
            return ""

    def confirm(self, question: str, *, default: bool = False) -> bool:
        reply = self.answer(f"{question} {'[Y/n]' if default else '[y/N]'} ").lower()
        return default if not reply else reply in {"y", "yes"}

    def heading(self, number: int, title: str) -> None:
        self.io.say()
        self.io.say(f"{number}. {title}")

    # ------------------------------------------------------------ steps

    def run(self) -> int:
        self.io.say("OpenQuestAI setup. Every step can be skipped; run it again any time.")
        steps = (
            ("Anthropic API key", self.api_key),
            ("Local fallback model", self.local_model),
            ("Speech models", self.speech_models),
            ("Microphone", self.microphone),
            ("The window", self.window),
            ("Start at login", self.start_at_login),
            ("Name and monthly cap", self.name_and_cap),
            ("Rooms and projects", self.rooms),
        )
        try:
            for number, (title, step) in enumerate(steps, 1):
                self.heading(number, title)
                step()
        except KeyboardInterrupt:
            self.io.say("\nStopped. Run `vision setup` again to go on.")
            return 130
        self.io.say()
        found = checks.run_checks(self.config, self.system)
        self.io.say(doctor.as_text(found, self.config.assistant.name))
        return doctor.exit_code(found)

    def api_key(self) -> None:
        source = self.system.api_key_source()
        if source is None:
            self.io.say(
                f"{self.config.assistant.name} thinks with Claude, through an API key "
                "from console.anthropic.com."
            )
            wanted = self.confirm("Store a key in the macOS Keychain now?", default=True)
        else:
            self.io.say(f"A key is stored in {checks.KEY_SOURCES.get(source, source)}.")
            wanted = self.confirm("Replace it with a new one?")
        if wanted:
            try:
                key = self.io.secret("Anthropic API key (input hidden): ").strip()
            except EOFError:
                key = ""
            if not key:
                self.io.say("Nothing stored.")
            else:
                self.system.store_key(key)
                self.io.say("Stored in the Keychain.")
        if self.system.api_key_source() is None:
            return
        if self.confirm("Check the key with one small API call (listing models, not billed)?"):
            verdict = self.system.verify_key()
            self.io.say({
                "accepted": "The API accepted the key.",
                "refused": "The API refused the key. Store another with `vision auth`.",
                "unreachable": "The API could not be reached; try again when online.",
            }.get(verdict, "No key to check."))

    def local_model(self) -> None:
        found = checks.local_model(self.config, self.system)
        if found.status == "ok":
            self.io.say(f"Done: {found.detail}.")
            return
        if not self.system.has_module("mlx_lm"):
            self.io.say("The local model needs `uv sync --extra local`. Skipping.")
            return
        repo = self.config.brain.local_model
        size = self.system.download_size([repo])
        self.io.say(f"{repo} answers when Claude cannot. Download: "
                    f"{gigabytes(size) if size else LOCAL_ESTIMATE}.")
        if self.confirm("Download it now?"):
            self.attempt("Downloading", lambda: self.system.download_local_model(self.config))

    def speech_models(self) -> None:
        repos = VoiceSettings.from_config(self.config).model_repos()
        missing = [r for r in repos if self.system.cached_size(r) is None]
        if not missing:
            self.io.say("Done: all speech models are downloaded.")
            return
        if not self.system.has_module("mlx_audio"):
            self.io.say("Speech needs `uv sync --extra voice`. Skipping.")
            return
        size = self.system.download_size(missing)
        self.io.say(f"Missing: {', '.join(missing)}. Download: "
                    f"{gigabytes(size) if size else checks.SPEECH_ESTIMATE}.")
        if self.confirm("Download them now?"):
            self.attempt("Downloading", lambda: self.system.download(missing))

    def microphone(self) -> None:
        if not self.system.has_module("sounddevice"):
            self.io.say("The microphone check needs `uv sync --extra voice`. Skipping.")
            return
        self.io.say("The check records three seconds, then says back what it heard. "
                    "macOS may ask for microphone permission.")
        if self.confirm("Run the microphone check?"):
            self.attempt("Listening", self.system.mic_check)

    def window(self) -> None:
        found = checks.window(self.config, self.system)
        if found.status == "ok":
            self.io.say(f"Done: {found.detail}.")
            return
        if self.system.find("npm") is None:
            self.io.say(f"Not built. {found.fix[0].upper()}{found.fix[1:]}.")
            return
        if self.confirm("Build the window now (npm ci and npm run build in web/)?"):
            built = self.attempt("Building", self.system.build_window)
            if built is not None:
                self.io.say("Built." if built else "The build failed; its output is above.")

    def start_at_login(self) -> None:
        found = checks.start_at_login(self.config, self.system)
        if found.status == "ok":
            self.io.say(f"Done: {self.config.assistant.name} starts at login.")
            return
        name = self.config.assistant.name
        self.io.say(f"A LaunchAgent in ~/Library/LaunchAgents starts {name} when you log in "
                    "and restarts it if it stops. `vision uninstall` removes it.")
        if self.confirm(f"Start {name} at login?"):
            path = self.attempt("Installing", lambda: self.system.install_agent(self.config))
            if path is not None:
                self.io.say(f"Installed {path}.")

    def name_and_cap(self) -> None:
        current = self.config.assistant.name
        name = self.answer(f"The assistant's name [{current}]: ") or current
        cap_now = self.config.budget.monthly_cap_usd
        cap = cap_now
        while True:
            reply = self.answer(f"Monthly API spending cap in dollars [{cap_now:g}]: ")
            if not reply:
                break
            try:
                cap = float(reply.removeprefix("$"))
            except ValueError:
                cap = -1.0
            if math.isfinite(cap) and cap >= 0:
                break
            self.io.say("A cap is a number of dollars, 0 or more, like 150.")
        path = self.config.paths.config_file
        if name != current:
            update_config(path, "assistant", {"name": name})
        if cap != cap_now:
            update_config(path, "budget", {"monthly_cap_usd": cap})
        if name != current or cap != cap_now:
            self.config = load_config(self.config.paths.home)
            self.io.say(f"Saved in {path}. A running daemon picks it up when restarted.")
        else:
            self.io.say("Unchanged.")

    def rooms(self) -> None:
        if not self.confirm("Attach a project folder to a room?"):
            return
        self.io.say(TOOLS_NOTE.format(name=self.config.assistant.name))
        while True:
            try:
                plan_rooms = _plan_rooms(self.config)
            except HouseError as exc:
                self.io.say(f"The house file has an error, so rooms cannot be changed: {exc}")
                return
            for r in plan_rooms:
                self.io.say(f"  {r['id']:<14} {r['name']:<16} {r['project'] or '(no project)'}")
            choice = self.answer("Room (id or name; blank to finish): ").casefold()
            if not choice:
                return
            room = next((r for r in plan_rooms if choice in {r["id"], r["name"].casefold()}), None)
            if room is None:
                self.io.say(f"There is no room called {choice!r}.")
                continue
            self.attach(room)

    def attach(self, room: dict[str, Any]) -> None:
        typed = self.answer("Project folder: ")
        if not typed:
            return
        folder = Path(typed).expanduser()
        if not folder.is_dir():
            self.io.say(f"{typed} is not a folder.")
            return
        project = typed if typed.startswith("~") else str(folder.resolve())
        fields: dict[str, Any] = {"project": project}
        refs = tool_refs(propose_tools(folder))
        if refs:
            shown = ", ".join(r["title"] + ("" if r["available"] else " (not installed)")
                              for r in refs)
            self.io.say(f"Proposed tools: {shown}.")
            if self.confirm("Use all of them?", default=True):
                fields["tools"] = [r["id"] for r in refs]
            else:
                fields["tools"] = [r["id"] for r in refs
                                   if self.confirm(f"  {r['title']}?", default=True)]
        else:
            self.io.say("No project tools recognised; the room keeps its agent's tools.")
        try:
            asyncio.run(_update_room(self.config, room["id"], fields))
        except HouseError as exc:
            self.io.say(f"Not saved: {exc}")
            return
        self.io.say(f"Saved: {room['name']} now works on {project}.")

    def attempt[T](self, doing: str, action: Callable[[], T]) -> T | None:
        """Run one fix; a failure is reported, None is returned and setup goes on."""
        self.io.say(f"{doing}...")
        try:
            return action()
        except Exception as exc:
            self.io.say(f"That did not work ({type(exc).__name__}: {exc}). Skipping.")
            return None


def _plan_rooms(config: Config) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = GridHouse(config, Bus()).plan()["rooms"]
    return rooms


async def _update_room(config: Config, room_id: str, fields: dict[str, Any]) -> None:
    house = GridHouse(config, Bus())
    try:
        await house.update_room(room_id, fields)
    finally:
        await house.close()


def run_setup(config: Config, system: System, io: Prompter | None = None) -> int:
    return Setup(config, system, io or Terminal()).run()
