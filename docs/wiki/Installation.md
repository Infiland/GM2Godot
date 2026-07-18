# Installation

> **Applies to:** GM2Godot 0.7.17 · GameMaker LTS 2026 · Godot 4.7.1
>
> **Last reviewed:** 2026-07-19

Use a packaged release for the desktop interface, or run from source when you also need the headless CLI. The current packaging and dependency details live in the repository's [release workflow](https://github.com/Infiland/GM2Godot/blob/main/.github/workflows/release.yml) and [`requirements.txt`](https://github.com/Infiland/GM2Godot/blob/main/requirements.txt).

Godot is not required merely to launch GM2Godot. Install the exact [Godot 4.7.1 release](https://github.com/godotengine/godot/releases/tag/4.7.1-stable) separately to open or headlessly validate converted output.

## Install a packaged release

Download the asset for your operating system from [GitHub Releases](https://github.com/Infiland/GM2Godot/releases). Extract downloaded archives before launching the application.

| Operating system | Release asset | Launch |
| --- | --- | --- |
| Windows | `GM2Godot-windows.zip` | Extract the archive, then run `GM2Godot.exe`. |
| macOS | `GM2Godot-macos.dmg` or `GM2Godot-macos.zip` | Open the DMG and copy `GM2Godot.app` to Applications, or extract the ZIP and launch the app. |
| Linux | `GM2Godot-linux.zip` | Extract the archive and run `./GM2Godot`. If the executable bit was lost during download or extraction, run `chmod +x GM2Godot` once. |

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

After launch, confirm that the title bar or **Help → About GM2Godot** shows version `0.7.17`.

## Run from source

GM2Godot requires Python 3.12 or later. The automated builds and tests use Python 3.12, so that is the most predictable choice. Git is required for the clone commands below.

### Windows (PowerShell)

```powershell
git clone https://github.com/Infiland/GM2Godot.git
Set-Location GM2Godot
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If the `py` launcher is unavailable, use a Python 3.12-or-later executable in its place. Activate the same environment again before running GM2Godot in a new terminal.

### macOS

```bash
git clone https://github.com/Infiland/GM2Godot.git
cd GM2Godot
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

### Linux

```bash
git clone https://github.com/Infiland/GM2Godot.git
cd GM2Godot
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

## Verify the source installation

With the virtual environment active, check the installed checkout without starting the GUI:

```bash
python main.py --version
python main.py list-converters
```

The first command should print `GM2Godot 0.7.17`; the second should list the conversion groups and the exact converter keys accepted by `--only`. The same CLI is also available through `python -m src.cli`.

Continue with [Quick Start Conversion](Quick-Start-Conversion). If launch or dependency setup fails, see [Diagnostics and Troubleshooting](Diagnostics-and-Troubleshooting).
