"""Delete all data: what the app keeps on this Mac goes for good, then the daemon stops.

Unlike Start over (`reset.py`), nothing is backed up. It is reached only from
the window, through `POST /api/delete-all` behind the token, with `confirm`
set to `CONFIRM`; it is not a tool, so no agent, automation or phone message
can call it. In this order:

1. What writes stops: the phone channel, the scheduler, jobs in progress,
   voice and the session, and the log database closes (`Daemon.stop`).
2. The API key and the phone's bot token leave the Keychain. A failure is
   reported in the answer and the rest goes on.
3. Only when asked: the speech models and local chat models this app uses or
   lists (`model_repos`) leave the Hugging Face cache, through the same
   removal as Settings' Delete (`Outside.delete_local`). The rest of the
   cache is shared with other tools and stays.
4. The LaunchAgent `vision install` wrote is removed (`Agent`, which tests
   replace). When this daemon is that agent's own process, only the plist
   goes now and the agent is unloaded after the answer, because unloading it
   ends this process.
5. The data folder: every file and folder the app makes there (`owned`),
   then the folder itself when nothing else is left. Anything else stays and
   is listed. Links are removed, never followed (only the espeak link is the
   app's own). A home that is `/`, the user's home folder or a folder above
   it is refused before anything happens.
6. The answer says what went and what stayed; the daemon stops itself
   `EXIT_DELAY_S` after it is sent, which leaves the window time to tell the
   Mac app to quit first.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from vision.brains import catalog
from vision.brains.budget import FILE_NAME as BUDGET_FILE
from vision.core import launchd
from vision.core.config import Config
from vision.jobs.store import FILE_NAME as JOBS_FILE
from vision.proposals.made import FOLDER as MADE_TOOLS
from vision.proposals.store import FILE_NAME as PROPOSALS_FILE
from vision.remote.store import FILE_NAME as PHONE_FILE
from vision.scheduler.store import FILE_NAME as AUTOMATIONS_FILE
from vision.settings.downloads import repo_bytes
from vision.settings.outside import Outside
from vision.setup import hf_cache
from vision.voice.settings import VoiceSettings

if TYPE_CHECKING:
    from vision.app import Daemon

log = logging.getLogger(__name__)

CONFIRM = "delete all data"
"""The value `confirm` must have; anything else is refused."""
EXIT_DELAY_S = 2.0
"""How long after the answer the daemon stops."""

ESPEAK_LINK = "espeak-ng-data"
"""The voice's short link to espeak-ng's data (`vision.voice.tts.ESPEAK_LINK`)."""
BACKUPS = "backups"
LOGS = "logs"
IMAGES = "images"
TOKEN = "token"
CONFIG = "config.toml"
HOUSE_FILE = "house.toml"
HOUSE = "house"
LOG_DB = "log.db"
DB_SIDES = ("-wal", "-shm", "-journal")
FINDER = ".DS_Store"
"""Finder's own view settings, made whenever someone opens the folder in Finder; never data."""

_LEFTOVERS = re.compile(
    r"^(?:"
    r"\.(?:config\.toml|house\.toml|proposals\.json)\..+\.tmp"  # an atomic write that was cut short
    r"|budget\.tmp"
    r"|(?:automations|jobs|phone|proposals)\.json\.(?:tmp|broken)"  # cut short, or set aside unreadable
    r"|\.espeak-ng-data\.\d+"  # the espeak link before it took its name
    r")$"
)
"""Files the app leaves beside its own when a write is cut short or a file could not be read."""

NOT_MADE = "The app did not make it."
NOT_AS_MADE = "It has a name the app uses, but the app did not make it this way (a link, say), so it was left alone."


class Agent(Protocol):
    """The LaunchAgent `vision install` writes."""

    def installed(self) -> bool: ...
    def runs_this_daemon(self) -> bool: ...
    def uninstall(self) -> None:
        """Unload it and remove its plist."""
        ...

    def remove_plist(self) -> None: ...
    def unload(self) -> None: ...


class MacAgent:
    """The real one, through `vision.core.launchd`."""

    def installed(self) -> bool:
        return launchd.installed()

    def runs_this_daemon(self) -> bool:
        return launchd.is_this_process()

    def uninstall(self) -> None:
        launchd.uninstall()

    def remove_plist(self) -> None:
        launchd.remove_plist()

    def unload(self) -> None:
        launchd.unload()


class Refused(ValueError):
    """Nothing was done; the message is for people."""


@dataclass(frozen=True, slots=True)
class Left:
    name: str
    why: str


@dataclass(slots=True)
class Cleared:
    removed: list[str] = field(default_factory=list)
    left: list[Left] = field(default_factory=list)
    folder_removed: bool = False


def owned(config: Config) -> tuple[frozenset[str], frozenset[str]]:
    """The names of the files and of the folders the app makes directly in the data folder.

    The house, the house file, the log and the logs folder follow `[paths]`
    when they stay in the data folder; ones moved elsewhere are `elsewhere`.
    """
    home = config.paths.home
    files = {CONFIG, HOUSE_FILE, TOKEN, BUDGET_FILE, AUTOMATIONS_FILE, JOBS_FILE, PHONE_FILE, PROPOSALS_FILE}
    files |= {LOG_DB + side for side in DB_SIDES} | {LOG_DB}
    folders = {HOUSE, LOGS, IMAGES, MADE_TOOLS, BACKUPS}
    paths = config.paths
    for path, into in ((paths.house, folders), (paths.logs, folders), (paths.house_file, files)):
        if path.parent == home:
            into.add(path.name)
    if paths.log_db.parent == home:
        files |= {paths.log_db.name} | {paths.log_db.name + side for side in DB_SIDES}
    return frozenset(files), frozenset(folders)


def elsewhere(config: Config) -> list[str]:
    """The app's data that `[paths]` keeps outside the data folder and that exists; it is not removed."""
    paths = config.paths
    home = Path(os.path.realpath(paths.home))
    found = []
    for path in (paths.house, paths.house_file, paths.log_db, paths.logs):
        real = Path(os.path.realpath(path))
        if not real.is_relative_to(home) and os.path.lexists(path):
            found.append(str(path))
    return found


def danger(home: Path, user_home: Path) -> str | None:
    """Why the data folder must not be emptied, or None."""
    real = Path(os.path.realpath(home))
    user = Path(os.path.realpath(user_home))
    if real == Path(real.anchor):
        return f"The data folder is set to {home}, which is the whole disk. Nothing was deleted."
    if real == user or user.is_relative_to(real):
        return (
            f"The data folder is set to {home}, which is your home folder or a folder above it. "
            "Nothing was deleted."
        )
    return None


def clear(home: Path, files: frozenset[str], folders: frozenset[str]) -> Cleared:
    """Remove what the app made in `home`, then `home` itself when it is empty. Follows no links."""
    done = Cleared()
    real = Path(os.path.realpath(home))
    if not real.is_dir():
        done.folder_removed = not os.path.lexists(home)
        return done
    with os.scandir(real) as entries:
        found = sorted(entries, key=lambda e: e.name)
    for entry in found:
        name = entry.name
        path = real / name
        link = entry.is_symlink()
        if name in folders and not link and entry.is_dir(follow_symlinks=False):
            problems: list[BaseException] = []
            shutil.rmtree(path, onexc=lambda _f, _p, exc: problems.append(exc))
        elif (name in files or name == FINDER or _LEFTOVERS.match(name)) and not link and entry.is_file(
            follow_symlinks=False
        ):
            _unlink(path)
        elif name == ESPEAK_LINK and link:
            _unlink(path)  # the link only; espeak's data stays where it is
        elif name in files or name in folders or name == ESPEAK_LINK:
            done.left.append(Left(name, NOT_AS_MADE))
            continue
        else:
            done.left.append(Left(name, NOT_MADE))
            continue
        if os.path.lexists(path):
            done.left.append(Left(name, "It could not be removed; check its permissions in Finder."))
        else:
            done.removed.append(name)
    if not done.left:
        try:
            real.rmdir()
        except OSError as exc:
            log.warning("the data folder stays: %s", exc)
        else:
            done.folder_removed = True
            if home.is_symlink():
                _unlink(home)
    return done


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("could not remove %s: %s", path.name, exc)


def model_repos(*configs: Config) -> list[str]:
    """The Hugging Face repos this app uses or lists: the speech models and the chosen local
    model of each config (the saved one and the running one), and the local model catalog."""
    repos: set[str] = set()
    for config in configs:
        repos |= set(VoiceSettings.from_config(config).model_repos())
        if config.brain.local_backend == "mlx":
            repos.add(config.brain.local_model)
    try:
        repos |= {m.id for m in catalog.load_catalog().models}
    except (OSError, ValueError) as exc:
        log.warning("the local model catalog is unreadable: %s", exc)
    return sorted(r for r in repos if hf_cache.REPO.match(r) and ".." not in r)


class Eraser:
    def __init__(
        self,
        daemon: Daemon,
        saved: Callable[[], Config],
        outside: Callable[[], Outside],
        downloading: Callable[[], set[str]],
    ) -> None:
        self._daemon = daemon
        self._saved = saved
        self._outside = outside
        self._downloading = downloading
        """The repos a download is writing now; they are not removed under it."""
        self.agent: Agent = MacAgent()
        self._lock = asyncio.Lock()
        self._unload_at_exit = False

    # ------------------------------------------------------------ what it would remove

    def preview(self) -> dict[str, Any]:
        """`GET /api/delete-all`: the data folder and the models on disk. Reads the disk; run it off the loop."""
        home = self._daemon.config.paths.home
        repos = model_repos(self._saved(), self._daemon.config)
        models = [{"repo": r, "bytes": n} for r in repos if (n := repo_bytes(r)) > 0]
        return {
            "home": os.path.realpath(home),
            "models": models,
            "models_bytes": sum(m["bytes"] for m in models),
        }

    # ------------------------------------------------------------ doing it

    async def erase(self, body: dict[str, Any]) -> dict[str, Any]:
        """Raises `Refused` before anything is done."""
        if body.get("confirm") != CONFIRM:
            raise Refused(f'Nothing was deleted. Send confirm as "{CONFIRM}" to delete all data.')
        models = body.get("models", False)
        if not isinstance(models, bool):
            raise Refused("Nothing was deleted. Send models as true or false.")
        d = self._daemon
        config = d.config
        home = config.paths.home
        async with self._lock:
            if d.erased:
                raise Refused("The data was already deleted. The assistant is stopping.")
            reason = danger(home, Path.home())
            if reason is not None:
                raise Refused(reason)
            saved = await asyncio.to_thread(self._saved)
            downloading = self._downloading()
            d.erased = True
            await d.stop()
            keychain = await self._keychain()
            removed_models = await self._models(saved, downloading) if models else None
            agent = await asyncio.to_thread(self._remove_agent)
            files, folders = owned(config)
            try:
                cleared = await asyncio.to_thread(clear, home, files, folders)
            except OSError as exc:
                log.warning("could not empty the data folder: %s", exc)
                cleared = Cleared(left=[Left(".", f"The data folder could not be read ({exc.strerror or exc}).")])
            outside = await asyncio.to_thread(elsewhere, config)
        answer = {
            "home": os.path.realpath(home) if not cleared.folder_removed else str(home),
            "removed": cleared.removed,
            "left": [asdict(x) for x in cleared.left],
            "folder_removed": cleared.folder_removed,
            "elsewhere": outside,
            "keychain": keychain,
            "models": removed_models,
            "launch_agent": agent,
        }
        answer["message"] = _message(answer)
        return answer

    async def finish(self) -> None:
        """After the answer is sent: wait a moment, unload the agent if it is this daemon, stop."""
        await asyncio.sleep(EXIT_DELAY_S)
        if self._unload_at_exit:
            await asyncio.to_thread(self.agent.unload)
        self._daemon.request_exit()

    async def _keychain(self) -> dict[str, Any]:
        failed: list[str] = []
        try:
            await asyncio.to_thread(self._outside().delete_key)
        except Exception as exc:
            log.warning("could not remove the API key from the Keychain: %s", type(exc).__name__)
            failed.append("the API key")
        try:
            await self._daemon.phone.delete_token()
        except Exception as exc:
            log.warning("could not remove the bot token from the Keychain: %s", type(exc).__name__)
            failed.append("the phone's bot token")
        if not failed:
            return {"ok": True, "message": "The API key and the phone's bot token are no longer in the Keychain."}
        return {
            "ok": False,
            "message": f"The Keychain did not let {' and '.join(failed)} be removed. Remove "
            f"{'it' if len(failed) == 1 else 'them'} in Keychain Access: the entries are named vision.",
        }

    async def _models(self, saved: Config, downloading: set[str]) -> dict[str, Any]:
        outside = self._outside()
        removed: list[str] = []
        left: list[dict[str, str]] = []
        freed = 0
        for repo in model_repos(saved, self._daemon.config):
            if repo in downloading:
                left.append({"repo": repo, "why": "It is still downloading."})
                continue
            try:
                n = await asyncio.to_thread(outside.delete_local, repo)
            except (OSError, ValueError) as exc:
                left.append({"repo": repo, "why": f"It could not be removed ({exc})."})
                continue
            if n > 0:
                removed.append(repo)
                freed += n
        return {"removed": removed, "left": left, "freed_bytes": freed}

    def _remove_agent(self) -> dict[str, Any]:
        try:
            if not self.agent.installed():
                return {"installed": False, "removed": False, "message": ""}
            if self.agent.runs_this_daemon():
                self.agent.remove_plist()
                self._unload_at_exit = True
            else:
                self.agent.uninstall()
        except Exception as exc:
            log.warning("could not remove the LaunchAgent: %s", exc)
            return {
                "installed": True,
                "removed": False,
                "message": f"The LaunchAgent could not be removed. Run `vision uninstall`, or delete "
                f"{launchd.plist_path()}.",
            }
        return {"installed": True, "removed": True, "message": "The LaunchAgent that started it at login is removed."}


def _message(answer: dict[str, Any]) -> str:
    """The answer in a few plain sentences."""
    said = []
    left = answer["left"]
    if answer["folder_removed"]:
        said.append("The data folder is gone.")
    elif left:
        names = ", ".join(x["name"] for x in left)
        said.append(f"Everything the app made in the data folder is gone. It still holds what the app did not make: {names}.")
    else:
        said.append("Everything the app made in the data folder is gone, but the folder itself could not be removed.")
    if answer["elsewhere"]:
        said.append(f"Settings kept some data outside it, which stays: {', '.join(answer['elsewhere'])}.")
    said.append(answer["keychain"]["message"])
    models = answer["models"]
    if models is not None:
        count = len(models["removed"])
        if count:
            what = "downloaded model was" if count == 1 else "downloaded models were"
            said.append(f"{count} {what} removed, {models['freed_bytes'] / 1e9:.1f} GB.")
        else:
            said.append("No downloaded models were on disk.")
        if models["left"]:
            said.append(f"Not removed: {', '.join(m['repo'] for m in models['left'])}.")
    if answer["launch_agent"]["message"]:
        said.append(answer["launch_agent"]["message"])
    said.append("The assistant stops now.")
    return " ".join(said)
