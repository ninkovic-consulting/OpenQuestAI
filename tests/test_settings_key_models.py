"""The API key (write-only) and the model list (API, cache, built-in)."""

from __future__ import annotations

import logging

import pytest
from settings_fakes import GOOD_KEY, FakeOutside, client, service, use

from vision.app import Daemon
from vision.core.config import load_config
from vision.settings.models_list import CACHE_S, ModelCatalog


def assert_secret_kept(key: str, texts: list[str], caplog: pytest.LogCaptureFixture) -> None:
    for text in texts:
        assert key not in text
    for record in caplog.records:
        assert key not in record.getMessage()


async def test_key_is_stored_verified_and_never_echoed(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = use(daemon)
    async with client(daemon) as http:
        stored = await http.post("/api/settings/key", json={"key": f"  {GOOD_KEY}\n"})
        settings = await http.get("/api/settings")
        models = await http.get("/api/models")
    assert stored.json() == {"stored": True, "source": "keychain", "verdict": "accepted"}
    assert fake.key == GOOD_KEY
    assert settings.json()["key"] == {"stored": True, "source": "keychain"}
    assert models.json()["source"] == "cache"
    assert fake.calls.count("list_models") == 1
    assert_secret_kept(GOOD_KEY, [stored.text, settings.text, models.text], caplog)
    assert service(daemon).key_replaced is False


async def test_a_badly_shaped_key_is_refused_without_echo(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = use(daemon)
    bad = "sk-proj-THIS-IS-SECRET-1234567890"
    async with client(daemon) as http:
        answer = await http.post("/api/settings/key", json={"key": bad})
        missing = await http.post("/api/settings/key", json={})
    assert answer.status_code == missing.status_code == 400
    assert "sk-ant-" in answer.json()["detail"]
    assert fake.calls == []
    assert_secret_kept(bad, [answer.text, missing.text], caplog)


@pytest.mark.parametrize("api", ["refused", "unreachable"])
async def test_key_verdicts(daemon: Daemon, api: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    use(daemon, FakeOutside(api=api))
    async with client(daemon) as http:
        stored = await http.post("/api/settings/key", json={"key": GOOD_KEY})
        verified = await http.post("/api/settings/key/verify")
    assert stored.json()["verdict"] == api
    assert verified.json() == {"verdict": api}
    assert_secret_kept(GOOD_KEY, [stored.text, verified.text], caplog)


class _ForgetfulKeychain(FakeOutside):
    """A Keychain that accepts the key without error and keeps nothing."""

    def store_key(self, key: str) -> None:
        self.calls.append("store_key")


async def test_a_key_the_keychain_did_not_keep_is_not_reported_stored(
    daemon: Daemon, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = use(daemon, _ForgetfulKeychain())
    async with client(daemon) as http:
        answer = await http.post("/api/settings/key", json={"key": GOOD_KEY})
    assert answer.status_code == 400
    assert "did not keep" in answer.json()["detail"]
    assert "list_models" not in fake.calls
    assert_secret_kept(GOOD_KEY, [answer.text], caplog)


async def test_replacing_a_key_asks_for_a_restart(daemon: Daemon) -> None:
    use(daemon, FakeOutside(key="sk-ant-old"))
    async with client(daemon) as http:
        await http.post("/api/settings/key", json={"key": GOOD_KEY})
        got = (await http.get("/api/settings")).json()
    assert got["restart_pending"] == ["key"]


async def test_verify_without_a_key(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        assert (await http.post("/api/settings/key/verify")).json() == {"verdict": "none"}


async def test_models_without_a_key_are_built_in(daemon: Daemon) -> None:
    fake = use(daemon)
    async with client(daemon) as http:
        got = (await http.get("/api/models")).json()
    assert got["source"] == "built_in" and got["fetched_at"] is None
    assert fake.calls == []
    by_id = {m["id"]: m for m in got["models"]}
    assert by_id["claude-opus-5-5"]["display_name"] == "Claude Opus 5.5"
    assert by_id["claude-opus-5-5"]["price"] == {"input_per_mtok": 4.0, "output_per_mtok": 20.0}
    assert by_id["claude-opus-5-5"]["retires_at"] is None
    sonnet = by_id["claude-sonnet-4-5"]
    assert sonnet["retires_at"] == "2026-11-30" and sonnet["price"] is None
    assert set(by_id) >= set(load_config().budget.prices)


async def test_models_from_the_api_then_the_cache(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(key=GOOD_KEY))
    async with client(daemon) as http:
        first = (await http.get("/api/models")).json()
        second = (await http.get("/api/models")).json()
    assert first["source"] == "api" and first["fetched_at"] is not None
    assert second["source"] == "cache" and second["fetched_at"] == first["fetched_at"]
    assert fake.calls.count("list_models") == 1
    new = next(m for m in first["models"] if m["id"] == "claude-brand-new")
    assert new == {
        "id": "claude-brand-new",
        "display_name": "Claude Brand New",
        "max_input_tokens": 200_000,
        "max_tokens": 64_000,
        "retires_at": None,
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "price": None,
    }
    assert first["models"][0]["price"] == {"input_per_mtok": 4.0, "output_per_mtok": 20.0}


async def test_offline_falls_back_to_the_cache_then_built_in() -> None:
    fake = FakeOutside(key=GOOD_KEY)
    clock = [1000.0]
    catalog = ModelCatalog(lambda: fake, now=lambda: clock[0])
    config = load_config()
    fake.api = "unreachable"
    assert (await catalog.listing(config))["source"] == "built_in"
    fake.api = "accepted"
    assert (await catalog.listing(config))["source"] == "api"
    clock[0] += CACHE_S + 1
    fake.api = "unreachable"
    stale = await catalog.listing(config)
    assert stale["source"] == "cache" and stale["fetched_at"] == 1000.0
    assert [m["id"] for m in stale["models"]] == ["claude-opus-5-5", "claude-brand-new"]
