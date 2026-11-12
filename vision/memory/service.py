"""`Memory` backed by the Markdown vault and the SQLite log."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from vision.core.config import Config
from vision.core.interfaces import AuditRecord, Hit, TurnRecord
from vision.memory.core import CoreBuilder
from vision.memory.log import Log
from vision.memory.vault import Vault

DEFAULT_CORE_BUDGET_CHARS = 12_000


class VaultMemory:
    """Settings read from `[paths]` extra keys: `persona` (a file, relative to the
    home directory) and `core_budget_chars`."""

    def __init__(self, config: Config) -> None:
        extra = config.paths.model_extra or {}
        persona = extra.get("persona")
        persona_path = None
        if persona:
            persona_path = Path(str(persona)).expanduser()
            if not persona_path.is_absolute():
                persona_path = config.paths.home / persona_path
        self._vault = Vault(config.paths.house, persona_path)
        self._log = Log(config.paths.log_db)
        self._core = CoreBuilder(
            self._vault, int(extra.get("core_budget_chars", DEFAULT_CORE_BUDGET_CHARS))
        )

    async def start(self) -> None:
        def run() -> None:
            self._vault.ensure()
            self._log.open()
            self._sync()

        await asyncio.to_thread(run)

    async def close(self) -> None:
        await asyncio.to_thread(self._log.close)

    def core(self) -> str:
        return self._core.text()

    async def remember(self, text: str) -> None:
        if not text.strip():
            return

        def run() -> None:
            self._vault.append_note(text, datetime.now())
            self._sync()

        await asyncio.to_thread(run)

    async def recall(self, query: str, limit: int = 5) -> list[Hit]:
        def run() -> list[Hit]:
            self._sync()
            return self._log.search(query, limit)

        return await asyncio.to_thread(run)

    async def log_turn(self, turn: TurnRecord) -> None:
        await asyncio.to_thread(self._log.add_turn, turn)

    async def audit(self, entry: AuditRecord) -> None:
        await asyncio.to_thread(self._log.add_audit, entry)

    async def history(self, limit: int = 50) -> list[TurnRecord]:
        return await asyncio.to_thread(self._log.history, limit)

    def _sync(self) -> None:
        v = self._vault
        self._log.sync_notes(v.note_stamps(), lambda rel: v.read_notes(v.root / rel))
