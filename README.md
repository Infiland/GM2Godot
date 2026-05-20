# GM2Godot

<img width="802" height="632" alt="screen" src="https://github.com/user-attachments/assets/cedf47f5-6668-44ab-8cf6-959a21afd7fa" />

GM2Godot is a modern, user-friendly tool designed to convert GameMaker (2024.14.2) projects to Godot (4.6.2) projects. It features a sleek dark-themed interface and intuitive controls for a seamless conversion experience.

## Features

- **Modern Dark Theme UI**: Clean, intuitive interface with modern design elements
- **Asset Conversion**: Converts various GameMaker assets to Godot format:
  - Sprites and Images
  - Sound Effects and Music
  - Fonts
  - Project Settings
  - Game Icons
  - Audio Bus Layout
  - Notes and Documentation
- **Platform Support**: Converts settings for multiple platforms:
  - Windows
  - macOS
  - Linux
- **Real-time Progress**: Visual feedback with progress bar and time tracking
- **Customizable Conversion**: Choose exactly which assets to convert
- **Compatibility Roadmap**: Tracks current and missing GameMaker-to-Godot coverage in [`todo-list/`](todo-list/README.md)

## What GM2Godot Is and Isn't

**GM2Godot is:**
- A modern asset conversion tool from GameMaker to Godot
- A growing GMS2+ GML-to-GDScript transpiler and Godot runtime compatibility layer
- A time-saver for starting Godot projects from GameMaker
- A tool for developers who want to migrate their projects

**GM2Godot isn't:**
- A perfect 1:1 conversion tool
- A complete implementation of every current GameMaker GML Code and GML Reference page yet
- A tool for converting compiled GM projects (use [UndertaleToolMod](https://github.com/UnderminersTeam/UndertaleModTool) instead)

## Compatibility Todo List

The full compatibility roadmap lives in [`todo-list/`](todo-list/README.md). It tracks checked current coverage, missing features, GMS2+ GML Code coverage, GML Reference/runtime API coverage, events, project import work, Godot architecture, and testing/codebase improvements.

## Releases

Downloadable releases include Windows (`.exe`), macOS (`.dmg` with `.app`), and Linux binaries. You can also run from source on Windows, macOS, and Linux.

To build a local macOS distributable (`.app` + `.dmg`), run `bash build_macos.sh` from the project root.

## Installation

### Prerequisites

- Python 3.9 or later

### Setup

1. **Clone the Repository**
```bash
git clone https://github.com/Infiland/GM2Godot
cd GM2Godot
```

2. **Create a Virtual Environment** (recommended)
```bash
python3 -m venv venv
```

3. **Activate the Virtual Environment**
- On macOS/Linux:
```bash
source venv/bin/activate
```
- On Windows:
```bash
venv\Scripts\activate
```

4. **Install Dependencies**
```bash
pip install -r requirements.txt
```

## Usage

1. **Launch the Application**
```bash
python main.py
```

2. **Configure Project Paths**
- Set your GameMaker project directory
- Set an empty Godot project directory
  - **Important**: Godot directory must be empty to prevent data loss

3. **Configure Settings**
- Click the "Settings" button to open the configuration window
- Select which assets to convert:
  - Assets (sprites, sounds, fonts)
  - Project (icons, settings, audio)
  - Work in Progress features
- Choose your target GameMaker platform

4. **Start Conversion**
- Click "Convert" to begin the process
- Monitor progress through the progress bar
- View detailed logs in the console
- Use the stop button if needed

## Contributing

We welcome contributions! Check out [CONTRIBUTING.md](https://github.com/Infiland/GM2Godot/blob/main/CONTRIBUTING.md) for guidelines.

To contribute:
1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to your branch
5. Create a Pull Request

## Support

- Report issues on our [GitHub Issues](https://github.com/Infiland/GM2Godot/issues) page
- Check our [Documentation](https://github.com/Infiland/GM2Godot/wiki) for detailed guides
- Join our community (Add community links if available)

---

## Instructions for Coding Agents (LLMs)

```text
You are setting up the GM2Godot project.

Ensure Python 3.9 or later is installed.

Create and activate a virtual environment:
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

Install dependencies from requirements.txt:
pip install -r requirements.txt

The project uses PySide6 (not Tkinter). Required packages are:
- Pillow
- markdown2
- requests
- PySide6

Run the application using:
python main.py

Verification for coding agents:
- If Python or generated-code logic changes, run ./venv/bin/pyright --warnings and relevant tests.
- For broad code changes, run ./venv/bin/python -m unittest.
- For documentation-only changes, do not run Pyright or tests unless explicitly requested.

Ensure all dependencies are installed correctly before execution.
```
