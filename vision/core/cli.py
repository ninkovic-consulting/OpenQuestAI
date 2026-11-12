"""The `vision` command.

    vision run [--fake-brain] [--port N]   run the daemon in the foreground
        [--voice-in IN.wav --voice-out OUT.wav [--voice-pace X]]
                                           (developer) hear a WAV file, speak into one
    vision status                          ask the running daemon how it is
    vision auth                            store the Anthropic API key in the Keychain
    vision setup                           download the local model (for the `mlx` backend)
    vision ui [--browser]                  open the window (or a browser tab)
    vision install [--dry-run]             install the LaunchAgent
    vision uninstall                       remove the LaunchAgent
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
import webbrowser
from pathlib import Path

import httpx

from vision.core import launchd, secrets
from vision.core.bus import Bus
from vision.core.config import Config, load_config
from vision.core.interfaces import Voice
from vision.core.token import read_token


def _base_url(config: Config, port: int | None) -> str:
    return f"http://127.0.0.1:{port or config.server.port}"


def cmd_run(config: Config, args: argparse.Namespace) -> int:
    from vision.app import Daemon  # heavy imports only when running the daemon

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if (args.voice_in is None) != (args.voice_out is None):
        print("--voice-in and --voice-out go together.")
        return 2
    voice = None
    if args.voice_in is not None:
        from vision.voice.filemode import make_file_voice

        def voice(config: Config, bus: Bus) -> Voice:
            return make_file_voice(config, bus, args.voice_in, args.voice_out, pace=args.voice_pace)

    daemon = Daemon(config, fake_brain=args.fake_brain, port=args.port, voice=voice)
    try:
        asyncio.run(daemon.serve())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_status(config: Config, args: argparse.Namespace) -> int:
    name = config.assistant.name
    print(f"home:      {config.paths.home}")
    print(f"api key:   {secrets.api_key_source() or 'none (run `vision auth`)'}")
    print(f"agent:     {'installed' if launchd.plist_path().exists() else 'not installed'}")
    token = read_token(config.paths.token)
    if token is None:
        print(f"daemon:    {name} has never run with this home")
        return 1
    headers = {"Authorization": f"Bearer {token}"}
    base = _base_url(config, args.port)
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=3) as client:
            health = client.get("/api/health").raise_for_status().json()
            state = client.get("/api/state").raise_for_status().json()
    except httpx.HTTPError as exc:
        print(f"daemon:    not reachable at {base} ({type(exc).__name__})")
        return 1
    budget = state["budget"]
    print(f"daemon:    up {health['uptime_s']}s at {base}, version {health['version']}")
    print(f"state:     {state['state']} on {state['brain']}")
    print(f"budget:    ${budget['spent_usd']:.2f} of ${budget['cap_usd']:.2f} in {budget['month']}")
    for notice in state["notices"][-5:]:
        print(f"notice:    [{notice['level']}] {notice['text']}")
    return 0


def cmd_auth(config: Config, args: argparse.Namespace) -> int:
    key = getpass.getpass("Anthropic API key (input hidden): ").strip()
    if not key:
        print("Nothing stored.")
        return 1
    secrets.store_api_key(key)
    print("Stored in the macOS Keychain. Restart the daemon to use it.")
    return 0


def cmd_setup(config: Config, args: argparse.Namespace) -> int:
    if config.brain.local_backend != "mlx":
        print(f"Nothing to set up: the local model is served by {config.brain.local_base_url}.")
        return 0
    try:
        from vision.brains.mlx_local import setup_model

        path, fetched = setup_model(config)
    except ImportError:
        print("The local model needs Apple Silicon and `uv sync --extra local`.")
        return 1
    except Exception as exc:
        print(f"Could not download {config.brain.local_model} ({type(exc).__name__}: {exc}).")
        return 1
    done = "already downloaded" if fetched is None else f"downloaded {fetched / 1e9:.1f} GB"
    print(f"{config.brain.local_model}: {done}, in {path}")
    return 0


class _Bridge:
    """Exposed to the page as `window.pywebview.api`."""

    def __init__(self, token: str) -> None:
        self._token = token

    def token(self) -> str:
        return self._token


def cmd_ui(config: Config, args: argparse.Namespace) -> int:
    token = read_token(config.paths.token)
    if token is None:
        print(f"{config.assistant.name} has not run yet; start it with `vision run` or `vision install`.")
        return 1
    url = _base_url(config, args.port) + "/"
    if args.browser:
        # The fragment never leaves the browser, so the token is not sent to any server.
        webbrowser.open(f"{url}#token={token}")
        return 0
    try:
        import webview
    except ImportError:
        print("The window needs pywebview: `uv sync --extra ui`, or use `vision ui --browser`.")
        return 1
    webview.create_window(
        config.assistant.name,
        url,
        js_api=_Bridge(token),
        fullscreen=True,
        frameless=True,
        background_color="#000000",
    )
    webview.start()
    return 0


def cmd_install(config: Config, args: argparse.Namespace) -> int:
    if args.dry_run:
        sys.stdout.write(launchd.plist_bytes(config, port=args.port).decode())
        print(f"\n(would write {launchd.plist_path()} and load it with launchctl)")
        return 0
    path = launchd.install(config, port=args.port)
    print(f"Installed and loaded {path}")
    return 0


def cmd_uninstall(config: Config, args: argparse.Namespace) -> int:
    path = launchd.uninstall()
    print(f"Unloaded and removed {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vision", description="The always-on assistant daemon.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the daemon in the foreground")
    run.add_argument("--fake-brain", action="store_true", help="answer with the scripted fake brain")
    run.add_argument("--port", type=int, help="override [server] port")
    run.add_argument("--voice-in", type=Path, help="(developer) hear this WAV instead of the mic")
    run.add_argument("--voice-out", type=Path, help="(developer) speak into this WAV file")
    run.add_argument(
        "--voice-pace", type=float, default=1.0, help="(developer) 1.0 is real time"
    )
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show whether the daemon is up and how it is")
    status.add_argument("--port", type=int)
    status.set_defaults(func=cmd_status)

    auth = sub.add_parser("auth", help="store the Anthropic API key in the Keychain")
    auth.set_defaults(func=cmd_auth)

    setup = sub.add_parser("setup", help="download the local model")
    setup.set_defaults(func=cmd_setup)

    ui = sub.add_parser("ui", help="open the window")
    ui.add_argument("--browser", action="store_true", help="open in the default browser instead")
    ui.add_argument("--port", type=int)
    ui.set_defaults(func=cmd_ui)

    install = sub.add_parser("install", help="install and load the LaunchAgent")
    install.add_argument("--dry-run", action="store_true", help="print the plist and do nothing")
    install.add_argument("--port", type=int)
    install.set_defaults(func=cmd_install)

    uninstall = sub.add_parser("uninstall", help="unload and remove the LaunchAgent")
    uninstall.set_defaults(func=cmd_uninstall)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(load_config(), args))
