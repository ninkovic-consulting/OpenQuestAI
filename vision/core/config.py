"""Configuration: built-in defaults overlaid by `$VISION_HOME/config.toml`.

`VISION_HOME` defaults to `~/.vision`. Tests and worktrees set it to a temp
directory so they never touch the real home.

Every section accepts extra keys, so an owner of a subsystem can read a new
setting with `config.voice.model_extra.get("my_key", default)` without
editing this file. Values in `config.toml` are merged over the defaults one
section at a time; tables inside a section (`[budget.prices.<model>]`,
`[gate.tiers]`) are merged key by key.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["free", "ask", "never"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="allow")


class AssistantConfig(_Section):
    name: str = "Vision"
    """Display name used in every user-facing string."""


class ServerConfig(_Section):
    host: str = "127.0.0.1"
    port: int = Field(default=7341, ge=1, le=65535)


class BrainConfig(_Section):
    talk_model: str = "claude-haiku-5-5"
    heavy_model: str = "claude-opus-5-5"
    local_backend: Literal["mlx", "openai"] = "mlx"
    """`mlx` runs `local_model` inside the daemon (Apple Silicon, `uv sync --extra local`);
    `openai` streams from an OpenAI-compatible server at `local_base_url`."""
    local_model: str = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    """A Hugging Face repo for `mlx`, or the server's model name for `openai`."""
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_idle_unload_s: float = Field(default=600.0, gt=0)
    """`mlx` only: free the model's memory after this long without a local turn."""
    local_context_tokens: int = Field(default=32_768, ge=1024)
    """`mlx` only: the most tokens of prompt and reply given to the model at once."""
    max_output_tokens: int = 1024
    """Per-reply output limit (spec section 11, runaway spend)."""
    request_timeout_s: float = 30.0
    retry_claude_after_s: float = 300.0
    """Cool-down before the router tries Claude again after falling back."""


class Price(_Section):
    """US dollars per million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float = 0.0
    cache_write_per_mtok: float = 0.0


def _default_prices() -> dict[str, Price]:
    # List prices checked 2026-11-12. Cache write is 1.25x input (5-minute TTL).
    return {
        "claude-haiku-5-5": Price(
            input_per_mtok=0.10,
            output_per_mtok=0.50,
            cache_read_per_mtok=0.01,
            cache_write_per_mtok=0.125,
        ),
        "claude-sonnet-5-5": Price(
            input_per_mtok=2.00,
            output_per_mtok=10.00,
            cache_read_per_mtok=0.10,
            cache_write_per_mtok=2.50,
        ),
        "claude-opus-4-8": Price(
            input_per_mtok=5.00,
            output_per_mtok=25.00,
            cache_read_per_mtok=0.50,
            cache_write_per_mtok=6.25,
        ),
        "claude-opus-5-5": Price(
            input_per_mtok=4.00,
            output_per_mtok=20.00,
            cache_read_per_mtok=0.20,
            cache_write_per_mtok=5.00,
        ),
    }


def ceiling_price(prices: dict[str, Price]) -> Price:
    """The highest known rate for each kind of token, for models missing from the table.

    An unknown model is never counted as free: it is priced at least as high as
    every model in the table.
    """
    return Price(
        input_per_mtok=max((p.input_per_mtok for p in prices.values()), default=0.0),
        output_per_mtok=max((p.output_per_mtok for p in prices.values()), default=0.0),
        cache_read_per_mtok=max((p.cache_read_per_mtok for p in prices.values()), default=0.0),
        cache_write_per_mtok=max((p.cache_write_per_mtok for p in prices.values()), default=0.0),
    )


class BudgetConfig(_Section):
    monthly_cap_usd: float = Field(default=150.0, ge=0)
    warn_fraction: float = Field(default=0.8, ge=0, le=1)
    prices: dict[str, Price] = Field(default_factory=_default_prices)


class VoiceConfig(_Section):
    enabled: bool = True
    sample_rate: int = 16_000
    vad_silence_ms: int = 600
    wake_phrases: list[str] = Field(default_factory=lambda: ["hey vision", "vision"])
    stop_phrases: list[str] = Field(default_factory=lambda: ["vision stop", "stop", "cancel"])
    followup_window_s: float = 20.0


class GateConfig(_Section):
    timeout_s: float = 60.0
    default_tier: Tier = "ask"
    """Tier for a tool that is not listed in `tiers`."""
    tiers: dict[str, Tier] = Field(
        default_factory=lambda: {
            "remember": "free",
            "recall": "free",
            "open_app": "free",
            "open_url": "free",
            "shell": "ask",
        }
    )


class PathsConfig(_Section):
    """Where runtime data lives. Relative paths are resolved against `home`."""

    home: Path
    house: Path = Path("house")
    """The memory vault (Markdown)."""
    house_file: Path = Path("house.toml")
    """The house layout and residents, owned by `vision.house`."""
    log_db: Path = Path("log.db")
    logs: Path = Path("logs")

    def model_post_init(self, __context: Any) -> None:
        for name in ("house", "house_file", "log_db", "logs"):
            value: Path = getattr(self, name).expanduser()
            setattr(self, name, value)
            if not value.is_absolute():
                setattr(self, name, self.home / value)

    @property
    def token(self) -> Path:
        return self.home / "token"

    @property
    def config_file(self) -> Path:
        return self.home / "config.toml"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    paths: PathsConfig
    agents: dict[str, Any] = Field(default_factory=dict)
    """Free-form; interpreted by `vision.house`, not validated here."""


def vision_home() -> Path:
    """`$VISION_HOME`, or `~/.vision`."""
    env = os.environ.get("VISION_HOME")
    return Path(env).expanduser() if env else Path.home() / ".vision"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(home: Path | None = None) -> Config:
    """Defaults overlaid by `<home>/config.toml` when it exists.

    `paths.home` always comes from `home` (or `VISION_HOME`), never from the file.
    """
    home = (home or vision_home()).expanduser()
    defaults = Config(paths=PathsConfig(home=home)).model_dump(mode="python")
    file = home / "config.toml"
    overrides: dict[str, Any] = {}
    if file.is_file():
        with file.open("rb") as fh:
            overrides = tomllib.load(fh)
    merged = _merge(defaults, overrides)
    merged["paths"] = {**merged["paths"], "home": home}
    return Config.model_validate(merged)
