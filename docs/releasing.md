# Releasing

How a merge to `main` becomes a download, how to do it by hand, how to change the version, and what is not signed yet.

## From merge to download

Two workflows live in `.github/workflows/`.

- **`ci.yml`** runs on every pull request and on every push to a branch other than `main`. On an Apple Silicon runner it installs uv and Python 3.12, runs `pytest`, then type-checks, tests and builds the window in `web/`. A newer push to the same branch cancels the run still in progress.
- **`release.yml`** runs on every push to `main` (a merge is one). Its `build` job, with read-only access, runs the same checks and then builds the standalone app (`vision app build --standalone`), verifies the signature with `codesign --verify --deep --strict`, zips it with `vision app package`, unzips the zip once to verify the signature survived, and keeps the zip as a workflow artifact. Its `publish` job, the only one that can write to the repository, creates a GitHub **pre-release** with the zip attached and then deletes all but the newest five of these pre-releases, with their tags.

A build is named by the version and the workflow's run number:

| What | Example |
|---|---|
| Release title | `Vision 0.1.0-beta (build 57)` |
| Tag | `v0.1.0-beta-build.57` |
| Zip | `Vision-0.1.0-beta-macos-arm64.zip` |
| App version line in Settings | `0.1.0-beta` (`CFBundleShortVersionString`) |
| App build number | `57` (`CFBundleVersion`) |

The latest build is the top entry on the Releases page. The "latest release" link (`/releases/latest`) ignores pre-releases, so it finds nothing while every build is a beta.

The run number comes from `VISION_BUILD_NUMBER`, which the workflow sets. A build made by hand without it has build number `0`.

## Making a release by hand

- **From GitHub:** Actions, Release, Run workflow, on `main`. It builds the head of `main` as a new build. Run on any other branch it builds and checks the app but does not publish.
- **On your own Mac**, for a copy that is not published:

  ```sh
  uv python install 3.12 && uv sync --all-extras
  cd web && npm ci && npm run build && cd ..
  VISION_BUILD_NUMBER=1 uv run --all-extras vision app build --standalone --out /tmp/vision-build
  codesign --verify --deep --strict /tmp/vision-build/Vision.app
  ```

  `vision app package` zips what is in `dist/` only, so to zip a build made elsewhere use `ditto -c -k --sequesterRsrc --keepParent Vision.app Vision.zip`.
- **To publish your own zip** (rarely needed): `gh release create v0.1.0-beta-build.N Vision-0.1.0-beta-macos-arm64.zip --prerelease --title "Vision 0.1.0-beta (build N)"`. Use a build number higher than the workflow's last one, or the pruning step will count it as old.

To keep a build for good, copy it elsewhere or edit its release and rename its tag: pruning only touches pre-releases whose tag ends in `-build.<number>`.

## Changing the version

The version is written in one place, `__version__` in `vision/__init__.py`, in the spelling Python packaging requires (PEP 440). `pyproject.toml` reads it from there. Everything people see is derived from it by `display_version()`:

| `__version__` | Shown as |
|---|---|
| `0.1.0b1` | `0.1.0-beta` |
| `0.1.0b2` | `0.1.0-beta.2` |
| `0.1.0rc1` | `0.1.0-rc` |
| `0.1.0` | `0.1.0` |

To bump it, change that one line, commit, and merge. Nothing else needs editing: not `pyproject.toml`, not `uv.lock`, not `macos/Info.plist`. The tests check that it is valid PEP 440 and that its displayed spelling follows the table. (`web/package.json` has its own version; it is private and shown nowhere.)

## What is signed, and what is not

- Every Mach-O file inside the app, and then the app bundle, is signed **ad hoc** (`codesign --sign -`). That makes the bundle's seal verifiable, which the workflow checks, and gives the app a stable identity by bundle id so macOS keeps its permissions across updates.
- It is **not** signed with a Developer ID certificate and **not notarised**. macOS therefore quarantines the download and blocks it the first time. The README's "Opening an app not signed with a Developer ID" says how to open it, and the release notes point there.
- The workflow does not run the app's `--self-test`: it needs a window, and a hosted runner has not been shown to give it one.

## What a Developer ID and notarisation would need

1. An Apple Developer Program membership, and a **Developer ID Application** certificate exported as a `.p12`.
2. Secrets in the repository (or, better, in a protected environment that needs approval): the `.p12` as base64 and its password, plus either an App Store Connect API key or an Apple ID, team id and app-specific password for `notarytool`.
3. In `release.yml`, a step that imports the certificate into a temporary keychain, used only by that job and deleted after it.
4. Changes to the build: in `vision/macapp/standalone.py`, `sign_machos` signs with the certificate, `--options runtime` (hardened runtime) and a secure timestamp instead of `--sign - --timestamp=none`. `macos/build.sh` does the same for the bundle, with the designated requirement dropped or changed to the team id. The bundled Python and MLX will probably need entitlements for the hardened runtime (for example `com.apple.security.cs.disable-library-validation` and `com.apple.security.cs.allow-unsigned-executable-memory`), to be found by trying.
5. After the zip: `xcrun notarytool submit Vision.zip --wait`, then `xcrun stapler staple Vision.app`, then zip again. The README's workaround section can then go.
6. `CFBundleShortVersionString` should then become plain numbers (`0.1.0`), as Apple documents it, and the Settings line should read a separate key for the `-beta` label. Today the label is in `CFBundleShortVersionString` because Settings reads that key and no Apple service checks it for an ad hoc build.

Whoever can change the workflow can then spend those secrets, so keep the signing step in a job on `main` only and limit who may push there.
