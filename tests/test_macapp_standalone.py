"""The standalone build, the package and the resource lookup, with the heavy steps faked.

No real uv, compiler, codesign or ditto runs: a fake runner records each call
and leaves behind what the real step would.
"""

from __future__ import annotations

import platform
import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from vision import display_version, macapp
from vision.core import cli, resources
from vision.core.config import Config
from vision.macapp import bundle, packaging, standalone

MACHO = bytes.fromhex("cffaedfe") + b"\0" * 12
PY = f"python{standalone.PYTHON_VERSION}"


class FakeRun:
    """Answers uv, compileall, codesign, the build script and ditto."""

    def __init__(self, fail: str = "") -> None:
        self.fail = fail
        self.calls: list[list[str]] = []
        self.signed: list[str] = []
        self.payload: Path | None = None

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        code = 1 if self.fail and self.fail in " ".join(argv) else 0
        if argv[1:3] == ["pip", "install"] and "--no-deps" in argv:
            python = Path(argv[argv.index("--python") + 1])
            site = python.parent.parent / "lib" / PY / "site-packages"
            (site / "vision").mkdir(parents=True)
            (site / "vision" / "__init__.py").write_text("")
            (site / "openquestai.dist-info").mkdir()
            (site / "openquestai.dist-info" / "direct_url.json").write_text("{}")
            (site / "mlx" / "include").mkdir(parents=True)
            (site / "mlx" / "include" / "kernel.h").write_text("")
            (site / "mlx" / "core.so").write_bytes(MACHO)
            (site / "numpy" / "tests").mkdir(parents=True)
            (site / "numpy" / "include").mkdir()
            (site / "numpy" / "include" / "arrayobject.h").write_text("")
            (site / "PyObjCTest").mkdir()
            (python.parent / "huggingface-cli").write_text("#!/build/python\n")
        elif argv[0] == "codesign":
            self.signed += argv[5:]
        elif argv[0] == "/bin/sh":
            self.payload = Path(kwargs["env"]["PAYLOAD"]) if "PAYLOAD" in kwargs["env"] else None
            (Path(argv[2]) / "Contents").mkdir(parents=True)
            (Path(argv[2]) / "Contents" / "Info.plist").write_bytes(Path(argv[3]).read_bytes())
        elif argv[0] == "/usr/bin/ditto":
            Path(argv[-1]).write_bytes(b"zip")
        return subprocess.CompletedProcess(argv, code, "", "")


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    """A miniature relocatable Python, as uv installs it."""
    root = tmp_path / "cpython"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / PY).write_bytes(MACHO)
    (root / "bin" / "python3").symlink_to(PY)
    (root / "bin" / "pip3").write_text("#!/x\n")
    (root / "bin" / "python3-config").write_text("")
    (root / "include").mkdir()
    lib = root / "lib"
    (lib / "tcl8.6").mkdir(parents=True)
    (lib / f"lib{PY}.dylib").write_bytes(MACHO)
    stdlib = lib / PY
    (stdlib / "tkinter").mkdir(parents=True)
    (stdlib / "__pycache__").mkdir()
    (stdlib / "__pycache__" / "os.cpython-312.pyc").write_bytes(b"old")
    (stdlib / "os.py").write_text("")
    (stdlib / "_sysconfigdata__darwin_darwin.py").write_text(f'BINDIR = "{root}/bin"\n')
    (stdlib / "site-packages" / "pip").mkdir(parents=True)
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "house" / "agents").mkdir(parents=True)
    (root / "house" / "default.toml").write_text("")
    (root / "web" / "dist").mkdir(parents=True)
    (root / "web" / "dist" / "index.html").write_text("<html>")
    (root / "web" / "dist" / "widget.html").write_text("<html>")
    return root


def test_stage_builds_the_payload(tmp_path: Path, runtime: Path, project: Path) -> None:
    run = FakeRun()
    out = standalone.stage(tmp_path / "stage", runtime=runtime, project=project,
                           uv=Path("/fake/uv"), run=run)
    python = out / "python"
    site = standalone.site_packages(python)

    assert (out / "house" / "default.toml").is_file()
    assert (out / "web" / "dist" / "index.html").is_file()
    assert (out / "web" / "dist" / "widget.html").is_file()
    assert sorted(p.name for p in (python / "bin").iterdir()) == ["python3", PY]
    for gone in ["include", "lib/tcl8.6", f"lib/{PY}/tkinter", f"lib/{PY}/__pycache__",
                 f"lib/{PY}/site-packages/pip"]:
        assert not (python / gone).exists(), gone
    assert not (site / "numpy" / "tests").exists()
    assert not (site / "numpy" / "include" / "arrayobject.h").exists()
    assert (site / "mlx" / "include" / "kernel.h").is_file()  # MLX reads its headers
    assert not (site / "PyObjCTest").exists()
    assert not (site / "openquestai.dist-info" / "direct_url.json").exists()
    sysconfig = (python / "lib" / PY / "_sysconfigdata__darwin_darwin.py").read_text()
    assert str(runtime) not in sysconfig

    uv = [c for c in run.calls if c[0] == "/fake/uv"]
    assert uv[0][1] == "export" and "--all-extras" in uv[0] and "--frozen" in uv[0]
    assert uv[1][-2:] == ["--requirement", str(tmp_path / "stage" / "requirements.txt")]
    assert uv[2][-2:] == ["--no-deps", str(project)]
    assert all("--break-system-packages" in c for c in uv[1:])
    assert not (tmp_path / "stage" / "requirements.txt").exists()

    compile_call = next(c for c in run.calls if "compileall" in c)
    assert "unchecked-hash" in compile_call and compile_call[0] == str(python / "bin" / PY)
    assert sorted(Path(p).name for p in run.signed) == ["core.so", f"lib{PY}.dylib", PY]


@pytest.mark.parametrize("page", ["index.html", "widget.html"])
def test_stage_needs_the_window(tmp_path: Path, runtime: Path, project: Path, page: str) -> None:
    """The house and the floating widget are both built pages; either missing stops the build."""
    (project / "web" / "dist" / page).unlink()
    with pytest.raises(macapp.AppBuildError, match="npm run build"):
        standalone.stage(tmp_path / "s", runtime=runtime, project=project,
                         uv=Path("/fake/uv"), run=FakeRun())


def test_stage_reports_a_failed_install(tmp_path: Path, runtime: Path, project: Path) -> None:
    with pytest.raises(macapp.AppBuildError, match="uv pip install"):
        standalone.stage(tmp_path / "s", runtime=runtime, project=project,
                         uv=Path("/fake/uv"), run=FakeRun(fail="--requirement"))


def test_build_standalone_hands_the_payload_over(
    config: Config, tmp_path: Path, runtime: Path, project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    swiftc = tmp_path / "swiftc"
    swiftc.touch()
    monkeypatch.setattr(standalone, "runtime_prefix", lambda: runtime)
    monkeypatch.setattr(standalone, "find_program", lambda name: Path("/fake/uv"))
    monkeypatch.setattr(bundle, "find_swiftc", lambda run: swiftc)
    run = FakeRun()
    dist = tmp_path / "dist"
    app = standalone.build_standalone(config, project=project, dist=dist, run=run)

    assert run.payload == dist / ".standalone"
    assert not run.payload.exists()  # the staging folder is removed afterwards
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["VisionStandalone"] is True
    assert info["VisionHome"] == "~/Library/Application Support/Vision" and info["VisionProjectPath"] == ""
    assert packaging.is_standalone(app)


def test_runtime_must_be_relocatable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.base_prefix", str(tmp_path))
    with pytest.raises(macapp.AppBuildError, match="uv python install"):
        standalone.runtime_prefix()


def test_thin_plist_is_not_standalone(config: Config, tmp_path: Path) -> None:
    info = plistlib.loads(bundle.info_plist(config, project=tmp_path))
    assert info["VisionStandalone"] is False
    assert info["VisionHome"] == str(config.paths.home)


def test_package_needs_the_standalone_app(config: Config, tmp_path: Path) -> None:
    with pytest.raises(macapp.AppBuildError, match="--standalone"):
        packaging.package(config, dist=tmp_path, run=FakeRun())
    app = tmp_path / "Vision.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"VisionStandalone": False}))
    with pytest.raises(macapp.AppBuildError, match="--standalone"):
        packaging.package(config, dist=tmp_path, run=FakeRun())
    (app / "Info.plist").write_bytes(plistlib.dumps({"VisionStandalone": True}))
    run = FakeRun()
    out = packaging.package(config, dist=tmp_path, run=run)
    assert out.name == f"Vision-{display_version()}-macos-{platform.machine()}.zip"
    assert run.calls[-1][:5] == ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent"]


def test_resources_follow_the_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(resources.ENV, raising=False)
    assert not resources.standalone()
    assert resources.house_dir() == resources.SOURCE_ROOT / "house"
    assert (resources.house_dir() / "default.toml").is_file()
    monkeypatch.setenv(resources.ENV, str(tmp_path))
    assert resources.standalone()
    assert resources.house_dir() == tmp_path / "house"
    assert resources.web_dist() == tmp_path / "web" / "dist"
    assert resources.env_file() is None


def test_cli_build_standalone(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(macapp, "build_standalone", lambda c: Path("/fake/dist/Vision.app"))
    assert cli.main(["app", "build", "--standalone"]) == 0
    assert "Built /fake/dist/Vision.app" in capsys.readouterr().out
