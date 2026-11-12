from pathlib import Path

from vision.core.config import Config, load_config, vision_home


def test_defaults(isolated_env: Path) -> None:
    config = load_config()
    assert vision_home() == isolated_env
    assert config.assistant.name == "Vision"
    assert (config.server.host, config.server.port) == ("127.0.0.1", 7341)
    assert config.brain.talk_model == "claude-haiku-5-5"
    assert config.brain.heavy_model == "claude-opus-5-5"
    assert config.brain.local_backend == "mlx"
    assert config.brain.local_model == "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    assert config.budget.monthly_cap_usd == 150
    assert config.budget.prices["claude-haiku-5-5"].input_per_mtok == 0.10
    assert config.gate.tiers["shell"] == "ask"
    assert config.paths.home == isolated_env
    assert config.paths.token == isolated_env / "token"
    assert config.paths.log_db == isolated_env / "log.db"
    assert config.paths.house == isolated_env / "house"
    assert config.paths.house_file == isolated_env / "house.toml"
    assert config.agents == {}


def test_file_overlays_defaults(isolated_env: Path) -> None:
    isolated_env.mkdir(parents=True)
    (isolated_env / "config.toml").write_text(
        """
[assistant]
name = "Ada"

[server]
port = 9000

[brain]
talk_model = "claude-sonnet-5-5"
my_extra = "kept"

[budget]
monthly_cap_usd = 20

[budget.prices.claude-haiku-5-5]
input_per_mtok = 0.2

[budget.prices.my-model]
input_per_mtok = 1
output_per_mtok = 2

[gate.tiers]
shell = "never"
open_app = "ask"

[paths]
home = "/elsewhere"
log_db = "data/log.db"
logs = "/var/tmp/vision-logs"

[agents.helper]
room = "library"
anything = [1, 2, 3]
""",
        encoding="utf-8",
    )
    config = load_config()
    assert config.assistant.name == "Ada"
    assert config.server.port == 9000
    assert config.server.host == "127.0.0.1"
    assert config.brain.talk_model == "claude-sonnet-5-5"
    assert config.brain.heavy_model == "claude-opus-5-5"
    assert config.brain.model_extra == {"my_extra": "kept"}
    assert config.budget.monthly_cap_usd == 20
    assert config.budget.prices["claude-haiku-5-5"].input_per_mtok == 0.2
    assert config.budget.prices["claude-haiku-5-5"].output_per_mtok == 0.50
    assert config.budget.prices["claude-opus-5-5"].output_per_mtok == 20
    assert config.budget.prices["my-model"].output_per_mtok == 2
    assert config.gate.tiers == {
        "remember": "free",
        "recall": "free",
        "open_app": "ask",
        "open_url": "free",
        "shell": "never",
    }
    assert config.paths.home == isolated_env  # never taken from the file
    assert config.paths.log_db == isolated_env / "data" / "log.db"
    assert config.paths.logs == Path("/var/tmp/vision-logs")
    assert config.agents == {"helper": {"room": "library", "anything": [1, 2, 3]}}


def test_explicit_home(tmp_path: Path) -> None:
    assert load_config(tmp_path / "x").paths.token == tmp_path / "x" / "token"


def test_voice_defaults_carry_no_assistant_name(config: Config) -> None:
    assert "wake_phrases" not in config.voice.model_dump()
    assert config.voice.stop_phrases == ["stop", "cancel"]
