"""The settings screen's state and changes, over the running daemon.

`SettingsService.outside` is the seam to the world (the Models API, the
Keychain, downloads, audio devices); tests replace it with a fake. The API
key passes through `store_key` once and is never kept, logged or returned.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from typing import TYPE_CHECKING, Any

from keyring.errors import KeyringError

from vision.core import effort
from vision.core.config import Config, load_config
from vision.gate.policy import FREE_AT_THE_MAC_ONLY, FREE_FOR_JOBS_FROM_THE_MAC, NEVER_FREE
from vision.house import HouseError, store
from vision.house.tools import load_catalog
from vision.memory import profile
from vision.settings import live, values
from vision.settings.downloads import Downloads
from vision.settings.local_models import LocalModels
from vision.settings.models_list import ModelCatalog, Verdict
from vision.settings.outside import MacOutside, Outside
from vision.settings.reset import Resetter
from vision.settings.voice_control import VoiceControl
from vision.setup import doctor
from vision.setup.checks import run_checks
from vision.voice.settings import LISTENING_MODES, listen_mode, listening_mode

if TYPE_CHECKING:
    from vision.app import Daemon

KEY_SHAPE = re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,300}$")
FIXABLE = ("local_model", "speech_models", "window")


class Refused(ValueError):
    """A request that cannot be done; the message is for people."""


class SettingsService:
    def __init__(self, daemon: Daemon, outside: Outside | None = None) -> None:
        self.daemon = daemon
        self.outside: Outside = outside or MacOutside()
        self.key_replaced = False
        """A key was stored over another; the brain keeps its client until a restart."""
        self.models = ModelCatalog(lambda: self.outside)
        self.voice = VoiceControl(daemon, lambda: self.outside)
        self.downloads = Downloads(self.saved, lambda: self.outside)
        self.local = LocalModels(daemon, self.saved, lambda: self.outside)
        self.resetter = Resetter(daemon, lambda: self.outside)
        self._window: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def config(self) -> Config:
        """The running config."""
        return self.daemon.config

    def saved(self) -> Config:
        """The config as config.toml holds it now; the running one if the file is broken.

        It differs from the running config in what only a restart applies. Reads a file.
        """
        try:
            return load_config(self.config.paths.home)
        except (OSError, ValueError):
            return self.config

    def restart_pending(self, saved: Config) -> list[str]:
        """Saved changes the running daemon has not taken up."""
        running = self.config
        pending = [
            field
            for field, (section, key) in values.CONFIG_KEYS.items()
            if field in values.RESTART_FIELDS
            and getattr(getattr(saved, section), key) != getattr(getattr(running, section), key)
        ]
        return [*pending, "key"] if self.key_replaced else pending

    # ------------------------------------------------------------ GET /api/settings

    async def settings(self) -> dict[str, Any]:
        c = self.config
        budget = self.daemon.components.budget.status()
        saved, local, voice, source = await asyncio.to_thread(self._disk_state)
        completed = getattr(c.assistant, "setup_completed", False) is True
        plan = self.daemon.components.house.plan()
        owner = await asyncio.to_thread(profile.read, c.paths.house)
        return {
            "assistant": {"name": c.assistant.name},
            "owner": owner.as_dict(),
            "models": {
                "talk": saved.brain.talk_model,
                "heavy": saved.brain.heavy_model,
                "talk_effort": saved.brain.talk_effort,
                "heavy_effort": saved.brain.heavy_effort,
                "local": local,
            },
            "budget": {
                **dataclasses.asdict(budget),
                "warn_fraction": c.budget.warn_fraction,
            },
            "agents": [{**a, "is_host": a["id"] == "host"} for a in plan["agents"]],
            "voice": voice,
            "gate": self._gate(),
            "jobs": {
                "max_running": c.jobs.max_running,
                "max_steps": c.jobs.max_steps,
                "timeout_s": c.jobs.job_timeout_s,
                "max_job_usd": c.jobs.max_job_usd,
                "speak_results": c.jobs.speak_results,
            },
            "projects": {"root": saved.projects.root},
            "key": {"stored": source is not None, "source": source},
            "setup": {"completed": completed, "first_run": source is None or not completed},
            "restart_pending": self.restart_pending(saved),
        }

    def _disk_state(self) -> tuple[Config, dict[str, Any], dict[str, Any], str | None]:
        saved = self.saved()
        brain = saved.brain
        size = None
        if brain.local_backend == "mlx":
            size = self.outside.cached_size(brain.local_model, "*.safetensors")
        local = {
            "backend": brain.local_backend,
            "model": brain.local_model,
            "downloaded": size is not None or brain.local_backend != "mlx",
            "size_bytes": size,
            "server": brain.local_base_url,
            "tools": self.daemon.local.known_tools(),
            "offline": brain.offline,
            "keep": brain.local_keep_loaded,
            "idle_s": brain.local_idle_unload_s,
        }
        return saved, local, self.voice.state(), self.outside.key_source()

    def _gate(self) -> dict[str, Any]:
        tiers = self.config.gate.tiers
        catalog = load_catalog()
        ids = [t for t, info in catalog.items() if info.built_in]
        ids += [t for t in tiers if t not in ids]
        ids = _after_shell(ids)
        return {
            "tools": [
                {
                    "id": t,
                    "title": catalog[t].title if t in catalog else t,
                    "description": catalog[t].description if t in catalog else "",
                }
                for t in ids
            ],
            "tiers": {t: tiers.get(t, self.config.gate.default_tier) for t in ids},
            "never_free": sorted(NEVER_FREE),
            "free_at_the_mac_only": sorted(FREE_AT_THE_MAC_ONLY),
            "free_for_jobs_from_the_mac": sorted(FREE_FOR_JOBS_FROM_THE_MAC),
        }

    # ------------------------------------------------------------ PATCH /api/settings

    async def patch(self, body: Any) -> dict[str, Any]:
        """Validate every field, then write and apply them. Raises `values.Invalid`."""
        async with self._lock:
            house = self.daemon.components.house
            agents = {a["id"] for a in house.plan()["agents"]}
            tools = {t["id"] for t in self._gate()["tools"]}
            change = _remember_listening(values.validate(body, agents=agents, tools=tools))
            saved = await asyncio.to_thread(self.saved)
            changed = [f for f, v in change if self._current(f, saved) != v]
            if "voice.listen" in changed and (said := await asyncio.to_thread(self.voice.listen_problem)):
                raise values.Invalid([{"field": "voice.listen", "message": said}])
            agent_changes = _agent_changes([(f, v) for f, v in change if f in changed])
            path = self.config.paths.config_file
            original = await asyncio.to_thread(values.read_doc, path)
            doc = values.with_change(original, change)
            try:
                fresh = values.config_from(self.config.paths.home, doc)
            except ValueError as exc:
                raise values.Invalid(
                    [{"field": "", "message": f"config.toml has a problem: {exc}"}]
                ) from None
            problems = await self.local.check(fresh, saved) + _effort_problems(fresh)
            if problems:
                raise values.Invalid(problems)
            if agent_changes:
                if not isinstance(house, live.EditableHouse):
                    raise values.Invalid(
                        [{"field": "agents", "message": "This house cannot be edited."}]
                    )
                try:
                    await house.update_agents(agent_changes)
                except HouseError as exc:
                    raise values.Invalid([{"field": "agents", "message": str(exc)}]) from None
            if doc != original:
                await asyncio.to_thread(store.write_toml, path, doc)
            owner = {f.removeprefix("owner."): v for f, v in change if f.startswith("owner.") and f in changed}
            if owner:
                await asyncio.to_thread(profile.update, self.config.paths.house, owner)
            await live.apply(self.daemon, fresh)
            if any(f.startswith("voice.") for f in changed):
                self.voice.forget()
            restart = [f for f in changed if f in values.RESTART_FIELDS]
            applied = [f for f in changed if f not in restart]
        return {
            "changed": changed,
            "applied": applied,
            "restart": restart,
            "settings": await self.settings(),
        }

    def _current(self, field: str, saved: Config) -> Any:
        if field.startswith("owner."):
            return getattr(profile.read(self.config.paths.house), field.removeprefix("owner."))
        if field.startswith("gate.tiers."):
            return saved.gate.tiers.get(field.removeprefix("gate.tiers."))
        if field.startswith("agents."):
            _, agent_id, key = field.split(".", 2)
            plan = self.daemon.components.house.plan()["agents"]
            return next(a[key] for a in plan if a["id"] == agent_id)
        if field == "voice.listen":
            return listen_mode(saved)
        if field == "voice.listening":
            return listening_mode(saved)
        section, key = values.CONFIG_KEYS[field]
        return getattr(getattr(saved, section), key, None)

    # ------------------------------------------------------------ the API key

    async def store_key(self, body: Any) -> dict[str, Any]:
        key = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str) or not KEY_SHAPE.match(key.strip()):
            raise Refused(
                "That does not look like an Anthropic API key. Keys start with sk-ant-; "
                "copy it again from console.anthropic.com, Settings, API keys."
            )
        key = key.strip()
        had_key = await asyncio.to_thread(self.outside.key_source) is not None
        try:
            await asyncio.to_thread(self.outside.store_key, key)
        except (KeyringError, OSError) as exc:
            raise Refused(
                f"The Keychain did not store the key ({type(exc).__name__}). Try again."
            ) from None
        source = await asyncio.to_thread(self.outside.key_source)
        if source != "keychain":
            raise Refused(
                "The Keychain did not keep the key, so nothing was stored. Unlock the Keychain "
                "and try again."
            )
        verdict = await self.models.fetch(key)
        self.key_replaced = self.key_replaced or had_key
        return {"stored": True, "source": source, "verdict": verdict}

    async def verify_key(self) -> dict[str, Verdict]:
        key = await asyncio.to_thread(self.outside.api_key)
        if key is None:
            return {"verdict": "none"}
        return {"verdict": await self.models.fetch(key)}

    # ------------------------------------------------------------ doctor

    async def doctor(self) -> dict[str, Any]:
        saved = await asyncio.to_thread(self.saved)
        checks = await asyncio.to_thread(run_checks, saved, self.outside.doctor_system())
        answer: dict[str, Any] = json.loads(doctor.as_json(checks))
        answer["fixable"] = [c.id for c in checks if c.id in FIXABLE and c.status != "ok"]
        return answer

    async def fix(self, check_id: Any) -> dict[str, Any]:
        if check_id in ("local_model", "speech_models"):
            await self.downloads.start(check_id)
            what = "local model" if check_id == "local_model" else "speech models"
            return {"started": True, "message": f"Downloading the {what} in the background."}
        if check_id == "window":
            if self._window is None or self._window.done():
                self._window = asyncio.create_task(self._build_window(), name="build-window")
            return {"started": True, "message": "Building the window; this takes a minute or two."}
        raise Refused(f"{check_id!r} cannot be fixed from here; follow the doctor's advice.")

    async def _build_window(self) -> None:
        built = await asyncio.to_thread(self.outside.build_window)
        if built:
            self.daemon.notice("info", "The window is built. Reload it to see the new version.")
        else:
            self.daemon.notice(
                "warn", "The window could not be built. Run `cd web && npm ci && npm run build`."
            )


def _effort_problems(fresh: Config) -> list[dict[str, str]]:
    """The host's efforts must be ones its talk and heavy models take."""
    brain = fresh.brain
    out = []
    for field, model, level in (
        ("models.talk_effort", brain.talk_model, brain.talk_effort),
        ("models.heavy_effort", brain.heavy_model, brain.heavy_effort),
    ):
        said = effort.problem(model, level)
        if said is not None:
            out.append({"field": field, "message": said})
    return out


def _remember_listening(change: values.Change) -> values.Change:
    """A listening mode chosen is also kept as the one the quick control goes back to."""
    fields = dict(change)
    listen = fields.get("voice.listen")
    if listen in LISTENING_MODES and "voice.listening" not in fields:
        return [*change, ("voice.listening", listen)]
    return change


def _agent_changes(change: values.Change) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for field, value in change:
        if field.startswith("agents."):
            _, agent_id, key = field.split(".", 2)
            out.setdefault(agent_id, {})[key] = value
    return out


def _after_shell(ids: list[str]) -> list[str]:
    """`ids` with the tools free only for jobs from the Mac moved to just after `shell`, so
    the two switches that run commands sit together in Asking first."""
    if "shell" not in ids:
        return ids
    moved = [t for t in ids if t in FREE_FOR_JOBS_FROM_THE_MAC]
    rest = [t for t in ids if t not in FREE_FOR_JOBS_FROM_THE_MAC]
    at = rest.index("shell") + 1
    return [*rest[:at], *moved, *rest[at:]]
