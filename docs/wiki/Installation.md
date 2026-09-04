# Installation

> **Applies to:** GM2Godot 0.7.72 · GameMaker LTS 2026 · Godot 4.7.2
>
> **Last reviewed:** 2026-09-04

Use a packaged release for the desktop interface, or run from source when you also need the headless CLI. The current packaging and dependency details live in the repository's [release workflow](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release.yml), [`requirements.txt`](https://github.com/Infiland/GM2Godot/blob/main/requirements.txt), and [native dependency-lock workflow](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/dependency-locks.yml).

Godot is not required merely to launch GM2Godot. Install the exact [Godot 4.7.2 release](https://github.com/godotengine/godot/releases/tag/4.7.2-stable) separately to open or headlessly validate converted output.

## Install a packaged release

Download the asset for your operating system from [GitHub Releases](https://github.com/Infiland/GM2Godot/releases). Extract downloaded archives before launching the application.

| Operating system | Release asset | Launch |
| --- | --- | --- |
| Windows | `GM2Godot-windows.zip` | Extract the archive, then run `GM2Godot.exe`. |
| macOS | `GM2Godot-macos.dmg` or `GM2Godot-macos.zip` | Open the DMG and copy `GM2Godot.app` to Applications, or extract the ZIP and launch the app. |
| Linux | `GM2Godot-linux.zip` | On the validated Ubuntu 24.04 x86_64 baseline, extract the archive and run `./GM2Godot`. If the executable bit was lost during download or extraction, run `chmod +x GM2Godot` once. |

Ubuntu 24.04 x86_64 is the only validated packaged-Linux baseline. PyInstaller does not bundle glibc, so glibc 2.39 is necessary; it is not by itself a portability guarantee for other distributions, which remain unverified and must also provide compatible system, OpenGL/EGL, and X11 libraries. The reviewed package manifest installs Ubuntu's `libegl1` and `libgl1` providers required by QtGui together with the XCB client libraries. The build rejects unresolved shared-library warnings and launches the executable extracted from the final ZIP through Qt's real `qxcb` platform under Xvfb before upload. A normal graphical X11 session, or XWayland when using a Wayland desktop, is still required at runtime.

On a minimal installation of that baseline, install the reviewed host libraries before launching the downloaded executable:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
  libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 \
  libxcb-util1 libxcb-xkb1
```

### Verify a release download

Releases starting with 0.7.14 include `SHA256SUMS`, with one SHA-256 digest for each of the four platform payloads. To verify the complete release, download all four payloads and `SHA256SUMS` into one directory, then run one of these commands from that directory:

```bash
# Linux
sha256sum --check --strict SHA256SUMS

# macOS
shasum -a 256 -c SHA256SUMS
```

On Windows, run `Get-FileHash -Algorithm SHA256 .\GM2Godot-windows.zip` in PowerShell and compare the result with the named `GM2Godot-windows.zip` line in `SHA256SUMS`. The manifest verifies the integrity of the published bytes; it is not a signature or proof of publisher identity.

The packaged builds are produced as windowed applications. For the CLI commands in this Wiki, use a source installation.

After launch, confirm that the title bar or **Help → About GM2Godot** shows version `0.7.72`. Click the version in the bottom information bar to browse the ten newest release changelogs; **Show more** appends the next ten.

## Run from source

Use the native, reproducible baseline for your host. Git is also required for the clone commands below.

| Host | Python | Constraint |
| --- | --- | --- |
| Linux x64 | CPython 3.12.13 | `constraints/requirements-linux-py312.lock` |
| macOS arm64 | CPython 3.12.10 | `constraints/requirements-macos-py312.lock` |
| Windows x64 | CPython 3.12.10 | `constraints/requirements-windows-py312.lock` |

Other Python patch versions and architectures are not the reviewed dependency baseline. Each procedure runs the bootstrap preflight before `venv` can invoke `ensurepip`; after activation, `python --version` must report the listed exact patch version before installation.

### Windows (PowerShell)

```powershell
git clone https://github.com/Infiland/GM2Godot.git
Set-Location GM2Godot
py -3.12 scripts/verify_dependency_bootstrap.py `
  --source requirements-bootstrap.txt `
  --policy stable `
  --constraint constraints/requirements-windows-py312.lock `
  --output (Join-Path $env:TEMP "gm2godot-bootstrap.json")
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python --version  # Python 3.12.10
$env:PIP_CONFIG_FILE = "nul"
python -m pip --isolated --disable-pip-version-check --no-input install `
  --no-cache-dir --only-binary=:all: `
  --constraint constraints/requirements-windows-py312.lock pip
python -m pip --isolated --disable-pip-version-check --no-input install `
  --no-cache-dir --only-binary=:all: `
  --constraint constraints/requirements-windows-py312.lock -r requirements.txt
python main.py
```

If the `py` launcher is unavailable, use an x64 CPython 3.12.10 executable directly. Activate the same environment again before running GM2Godot in a new terminal.

### macOS

```bash
git clone https://github.com/Infiland/GM2Godot.git
cd GM2Godot
python3.12 scripts/verify_dependency_bootstrap.py \
  --source requirements-bootstrap.txt \
  --policy stable \
  --constraint constraints/requirements-macos-py312.lock \
  --output "${TMPDIR:-/tmp}/gm2godot-bootstrap.json"
python3.12 -m venv venv
source venv/bin/activate
python --version  # Python 3.12.10
export PIP_CONFIG_FILE=/dev/null
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-macos-py312.lock pip
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-macos-py312.lock -r requirements.txt
python main.py
```

### Linux

```bash
git clone https://github.com/Infiland/GM2Godot.git
cd GM2Godot
mapfile -t qt_packages < <(
  sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' \
    packaging/linux/qt-xcb-runtime-packages.txt
)
sudo apt-get update
sudo apt-get install --yes --no-install-recommends "${qt_packages[@]}"
python3.12 scripts/verify_dependency_bootstrap.py \
  --source requirements-bootstrap.txt \
  --policy stable \
  --constraint constraints/requirements-linux-py312.lock \
  --output "${TMPDIR:-/tmp}/gm2godot-bootstrap.json"
python3.12 -m venv venv
source venv/bin/activate
python --version  # Python 3.12.13
export PIP_CONFIG_FILE=/dev/null
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-linux-py312.lock pip
python -m pip --isolated --disable-pip-version-check --no-input install \
  --no-cache-dir --only-binary=:all: \
  --constraint constraints/requirements-linux-py312.lock -r requirements.txt
python main.py
```

The null config file and `--isolated` prevent machine-local pip settings from changing the reviewed install behavior. `requirements-bootstrap.txt` is the sole reviewed source for the exact pip/pip-tools pair; preflight must match it to the selected native lock before any package installation. Requesting unversioned `pip` under that lock remains exact without another live version literal. The repository's [native dependency-lock workflow](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/dependency-locks.yml) accepts only a stable pair or an all-three-lock source transition, proves the proposed pair with a bootstrap-only install and self-host, then generates the complete candidate, self-host, and two clean-install receipts. A changed candidate intentionally fails the committed-equality gate after evidence upload; review and commit all three native `.lock` artifacts, then rerun. `refresh=package` rejects `pip` and `pip-tools`, and dependency changes are never auto-merged. Successful main runs submit the verified platform graphs under stable correlators so transitive security alerts remain available even though generated locks are hidden from Dependabot's pip updater. Do not generate one platform's lock from another platform. Current install and compile paths reject source distributions with `--only-binary=:all:` and disable pip's cache with `--no-cache-dir`, so pip 26.2's isolated-build and index-cache changes do not alter the locked graph. Any future source-build path must pass a separately reviewed `--build-constraint` for its isolated build environment.

## Verify the source installation

With the virtual environment active, check the installed checkout without starting the GUI:

```bash
python main.py --version
python main.py list-converters
```

The first command should print `GM2Godot 0.7.72`; the second should list the conversion groups and the exact converter keys accepted by `--only`. The same CLI is also available through `python -m src.cli`.

Continue with [Quick Start Conversion](Quick-Start-Conversion). If launch or dependency setup fails, see [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting).
