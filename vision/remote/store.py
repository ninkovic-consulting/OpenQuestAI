"""The phone channel's settings and pairing, `$VISION_HOME/phone.json`, private (0600).

The bot token is never here: it lives in the Keychain (`vision.remote.token`).
Written whole through a temporary file and a rename. A file that cannot be
read is moved aside (`phone.json.broken`) and the defaults are used, which
means unpaired. Blocking; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

FILE_NAME = "phone.json"
VERSION = 1

log = logging.getLogger(__name__)


@dataclass(slots=True)
class PhoneState:
    enabled: bool = True
    """The channel runs whenever a token is stored; False turns it off."""
    owner_id: str = ""
    """The paired owner's user id on the service; empty while unpaired."""
    owner_name: str = ""
    chat_id: str = ""
    """The direct-message chat with the owner."""
    paired_at: float = 0.0
    bot_id: str = ""
    bot_name: str = ""
    """The bot's id and name when the token was last checked."""
    notify_automations: bool = True
    notify_warnings: bool = True
    notify_approvals: bool = True
    notify_jobs: bool = True
    """Send the host's report of a job that was handed off from the phone."""
    speak_on_mac: bool = False
    """Speak replies to the phone on the Mac too."""
    voice_replies: bool = False
    """Answer a voice note with a voice note as well as text."""
    phone_tools: list[str] | None = None
    """Tools that may be approved from the phone; None is every tool but `shell` and
    `run_program`. A list saved before a tool existed does not hold it, so a new
    tool is approved from the phone only once the owner adds it."""

    @property
    def paired(self) -> bool:
        return bool(self.owner_id)

    def unpair(self) -> None:
        self.owner_id = self.owner_name = self.chat_id = ""
        self.paired_at = 0.0


_KNOWN = {f.name for f in fields(PhoneState)}


def path_for(home: Path) -> Path:
    return home / FILE_NAME


def load(path: Path) -> PhoneState:
    if not path.exists():
        return PhoneState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = PhoneState(**{k: v for k, v in data["phone"].items() if k in _KNOWN})
        _check(state)
        return state
    except (OSError, ValueError, KeyError, TypeError) as exc:
        broken = path.with_name(path.name + ".broken")
        log.warning("phone settings unreadable (%s); moved to %s", type(exc).__name__, broken)
        path.replace(broken)
        return PhoneState()


def _check(state: PhoneState) -> None:
    for name in ("owner_id", "owner_name", "chat_id", "bot_id", "bot_name"):
        if not isinstance(getattr(state, name), str):
            raise TypeError(name)
    tools = state.phone_tools
    if tools is not None and not (isinstance(tools, list) and all(isinstance(t, str) for t in tools)):
        raise TypeError("phone_tools")


def save(path: Path, state: PhoneState) -> None:
    body = json.dumps({"version": VERSION, "phone": asdict(state)}, indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(temp, 0o600)
    temp.replace(path)
