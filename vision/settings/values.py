"""Checking a settings change field by field, and turning it into config.toml values.

A change is a list of `(field, value)` pairs with dotted field names as the
window sends them (`budget.cap_usd`, `gate.tiers.shell`, `agents.maker.name`).
`validate` collects every problem before refusing, so the window can show
them all at once.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vision.core.config import Config, PathsConfig
from vision.gate.policy import ALWAYS_ASK

KOKORO_VOICES = (
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_lewis",
)
TIERS = ("free", "ask", "never")
NAME_MAX = 40
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$")
HF_REPO = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[\w.-]{1,95}$")
MAX_CAP_USD = 1_000_000.0
MAX_FOLLOWUP_S = 300.0
DEVICE_MAX = 200

CONFIG_KEYS: dict[str, tuple[str, str]] = {
    "assistant.name": ("assistant", "name"),
    "models.talk": ("brain", "talk_model"),
    "models.heavy": ("brain", "heavy_model"),
    "models.local": ("brain", "local_model"),
    "budget.cap_usd": ("budget", "monthly_cap_usd"),
    "voice.input_device": ("voice", "input_device"),
    "voice.output_device": ("voice", "output_device"),
    "voice.tts_voice": ("voice", "tts_voice"),
    "voice.followup_s": ("voice", "followup_window_s"),
    "setup.completed": ("assistant", "setup_completed"),
}
"""Dotted field -> (section, key) in config.toml. Gate tiers go to `[gate.tiers]`."""

RESTART_FIELDS = frozenset({"models.talk", "models.heavy", "models.local"})

Change = list[tuple[str, Any]]


class Invalid(ValueError):
    """One or more fields failed; `errors` are `{"field", "message"}` for the window."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


class _Bad(ValueError):
    pass


# ------------------------------------------------------------------ one value each


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _name(what: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not text or len(text) > NAME_MAX or any(ord(c) < 32 for c in text):
            raise _Bad(f"{what} must be 1 to {NAME_MAX} characters of plain text.")
        return text

    return check


def _model(value: Any) -> str:
    if not isinstance(value, str) or not MODEL_ID.match(value.strip()):
        raise _Bad("Choose a model from the list; a model id looks like claude-opus-5-5.")
    return value.strip()


def _local(value: Any) -> str:
    if not isinstance(value, str) or not HF_REPO.match(value.strip()):
        raise _Bad(
            "The local model must be a Hugging Face repo, like "
            "mlx-community/Qwen3-4B-Instruct-2507-4bit."
        )
    return value.strip()


def _cap(value: Any) -> float:
    if not _is_number(value) or not 0 <= value <= MAX_CAP_USD:
        raise _Bad("The monthly cap must be a number of dollars, 0 or more.")
    return float(value)


def _device(value: Any) -> str:
    if not isinstance(value, str) or len(value) > DEVICE_MAX:
        raise _Bad("Choose a device by its name, or leave it empty for the system default.")
    return value.strip()


def _tts_voice(value: Any) -> str:
    if value not in KOKORO_VOICES:
        raise _Bad(f"The voice must be one of: {', '.join(KOKORO_VOICES)}.")
    return str(value)


def _followup(value: Any) -> float:
    if not _is_number(value) or not 0 <= value <= MAX_FOLLOWUP_S:
        raise _Bad(
            f"The follow-up window must be a number of seconds from 0 to {MAX_FOLLOWUP_S:g}."
        )
    return float(value)


def _flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise _Bad("Send true or false.")
    return value


SECTIONS: dict[str, dict[str, Callable[[Any], Any]]] = {
    "assistant": {"name": _name("The assistant's name")},
    "models": {"talk": _model, "heavy": _model, "local": _local},
    "budget": {"cap_usd": _cap},
    "voice": {
        "input_device": _device,
        "output_device": _device,
        "tts_voice": _tts_voice,
        "followup_s": _followup,
    },
    "setup": {"completed": _flag},
}


# ------------------------------------------------------------------ the whole body


def validate(body: Any, *, agents: set[str], tools: set[str]) -> Change:
    """Every field of a PATCH body, checked. Raises `Invalid` listing all problems."""
    if not isinstance(body, dict):
        raise Invalid([{"field": "", "message": "The body must be a JSON object."}])
    errors: list[dict[str, str]] = []
    change: Change = []

    def check(field: str, fn: Callable[[Any], Any], value: Any) -> None:
        try:
            change.append((field, fn(value)))
        except _Bad as exc:
            errors.append({"field": field, "message": str(exc)})

    for section, values in body.items():
        if section not in {*SECTIONS, "agents", "gate"}:
            errors.append({"field": section, "message": f"There is no setting called {section!r}."})
        elif not isinstance(values, dict):
            errors.append({"field": section, "message": "Send this part as a JSON object."})
        elif section == "agents":
            _agents(values, agents, check, errors)
        elif section == "gate":
            _gate(values, tools, check, errors)
        else:
            for key, value in values.items():
                fn = SECTIONS[section].get(key)
                if fn is None:
                    errors.append(
                        {"field": f"{section}.{key}", "message": "There is no such setting."}
                    )
                else:
                    check(f"{section}.{key}", fn, value)
    if errors:
        raise Invalid(errors)
    return change


def _agents(
    values: dict[str, Any],
    known: set[str],
    check: Callable[[str, Callable[[Any], Any], Any], None],
    errors: list[dict[str, str]],
) -> None:
    for agent_id, fields in values.items():
        where = f"agents.{agent_id}"
        if agent_id not in known:
            errors.append({"field": where, "message": f"There is no agent with the id {agent_id!r}."})
            continue
        if not isinstance(fields, dict):
            errors.append({"field": where, "message": "Send the agent's settings as an object."})
            continue
        for key, value in fields.items():
            field = f"{where}.{key}"
            if key not in ("name", "model"):
                errors.append({"field": field, "message": "An agent has a name and a model."})
            elif agent_id == "host":
                follows = "the assistant's name" if key == "name" else "the talk model"
                errors.append(
                    {"field": field, "message": f"The host's {key} follows {follows}; change that."}
                )
            else:
                check(field, _name("An agent's name") if key == "name" else _model, value)


def _gate(
    values: dict[str, Any],
    tools: set[str],
    check: Callable[[str, Callable[[Any], Any], Any], None],
    errors: list[dict[str, str]],
) -> None:
    for key, tiers in values.items():
        if key != "tiers" or not isinstance(tiers, dict):
            errors.append({"field": f"gate.{key}", "message": "Send gate.tiers as an object."})
            continue
        for tool, tier in tiers.items():
            field = f"gate.tiers.{tool}"
            if tool not in tools:
                errors.append({"field": field, "message": f"There is no tool called {tool!r}."})
            elif tool in ALWAYS_ASK and tier == "free":
                errors.append(
                    {
                        "field": field,
                        "message": f"{tool} always asks first, so it can be ask or never, "
                        "but never free.",
                    }
                )
            else:
                check(field, _tier, tier)


def _tier(value: Any) -> str:
    if value not in TIERS:
        raise _Bad("A tier is free, ask or never.")
    return str(value)


# ------------------------------------------------------------------ config.toml


def read_doc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def with_change(doc: dict[str, Any], change: Change) -> dict[str, Any]:
    """A copy of the config.toml document with the change's config fields set."""
    out = merge({}, doc)
    for field, value in change:
        if field.startswith("gate.tiers."):
            out.setdefault("gate", {}).setdefault("tiers", {})[field.removeprefix("gate.tiers.")] = value
        elif field in CONFIG_KEYS:
            section, key = CONFIG_KEYS[field]
            out.setdefault(section, {})[key] = value
    return out


def config_from(home: Path, doc: dict[str, Any]) -> Config:
    """The config `load_config` would build if config.toml held `doc`. Raises on bad values."""
    defaults = Config(paths=PathsConfig(home=home)).model_dump(mode="python")
    merged = merge(defaults, doc)
    merged["paths"] = {**merged["paths"], "home": home}
    return Config.model_validate(merged)


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        elif isinstance(value, dict):
            out[key] = merge({}, value)
        else:
            out[key] = value
    return out
