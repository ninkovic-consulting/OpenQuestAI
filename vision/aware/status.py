"""The assistant's own setup and status, in words, for the `assistant_status` tool.

Built from what the settings screen already computes (`SettingsService.settings`:
models, spend, voice and microphone, the gate's tiers, whether a key is
stored), plus the automations, the phone channel and the daemon's paths.
Nothing secret is read: the API key only as "stored or not".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vision import __version__
from vision.scheduler.words import when

if TYPE_CHECKING:
    from vision.app import Daemon

_PHONE = {
    "off": "turned off",
    "no_token": "not set up (no bot token)",
    "connecting": "connecting",
    "online": "connected",
    "offline": "reconnecting",
    "refused": "stopped: the bot token was refused",
}


def brain_words(brain: str, models: dict[str, Any]) -> str:
    if brain == "claude":
        return f"Claude, talk model {models['talk']} (heavy model {models['heavy']} when asked to think something through)"
    if brain == "local":
        local = models["local"]
        return f"the local fallback model {local['model']} on this Mac, because Claude is unavailable or the monthly cap is reached"
    return "the scripted fake brain (a developer setting; nothing real answers)"


def voice_words(v: dict[str, Any]) -> str:
    if not v["installed"]:
        return "not installed"
    if not v["enabled"]:
        return "off"
    running = "on and listening" if v["running"] else "on, but the microphone loop is not running"
    mic = {"granted": "allowed", "denied": "refused by macOS", "unknown": "not known yet"}.get(v["mic"], v["mic"])
    return f"{running}; microphone access {mic}"


def status_text(d: Daemon, settings: dict[str, Any]) -> str:
    """`settings` is the answer of `GET /api/settings`."""
    c = d.config
    budget = settings["budget"]
    tiers: dict[str, str] = settings["gate"]["tiers"]
    asks = sorted(t for t, tier in tiers.items() if tier == "ask")
    never = sorted(t for t, tier in tiers.items() if tier == "never")
    automations = d.automations.all()
    due = sorted((a for a in automations if a.next_run is not None and not a.paused), key=lambda a: a.next_run or 0)
    paused = sum(1 for a in automations if a.paused)
    phone = d.phone.state
    lines = [
        f"Name: {settings['assistant']['name']}. App version {__version__}.",
        f"Answering now: {brain_words(d.components.brain.name, settings['models'])}.",
        f"API key: {'stored' if settings['key']['stored'] else 'not stored'}.",
        f"Spend this month ({budget['month']}): ${budget['spent_usd']:.2f} of the ${budget['cap_usd']:.2f} cap; "
        f"a warning comes at {budget['warn_fraction']:.0%}.",
        f"Voice: {voice_words(settings['voice'])}.",
        f"Automations: {len(automations)}" + (f", {paused} paused" if paused else "") + (
            f"; next due: {due[0].name} at {when(due[0].next_run or 0, d.automations.zone())}." if due else "; none due."
        ),
        f"Phone channel (Discord): {_PHONE.get(d.phone.connection, d.phone.connection)}; "
        + (f"paired with {phone.owner_name}." if phone.paired else "not paired."),
        f"Tools that ask first: {', '.join(asks) or 'none'}." + (f" Never allowed: {', '.join(never)}." if never else ""),
        f"Data lives in {c.paths.home}: memory vault {c.paths.house}, log {c.paths.log_db}, house file {c.paths.house_file}.",
    ]
    if settings["restart_pending"]:
        lines.append(f"Waiting for a restart: {', '.join(settings['restart_pending'])}.")
    if not settings["setup"]["completed"]:
        lines.append("Setup has not been finished in the window yet.")
    return "\n".join(lines)
