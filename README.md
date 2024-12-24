# GM2Godot

![GM2Godot 0 0 12](https://github.com/user-attachments/assets/b19edd23-f91e-48b7-a2c3-7e5654a8e9b8)

GM2Godot is a modern, user-friendly tool designed to convert GameMaker (2024.11) projects to Godot (4.3) projects. It features a sleek dark-themed interface and intuitive controls for a seamless conversion experience.

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

## What GM2Godot Is and Isn't

**GM2Godot is:**
- A modern asset conversion tool from GameMaker to Godot
- A time-saver for starting Godot projects from GameMaker
- A tool for developers who want to migrate their projects

**GM2Godot isn't:**
- A perfect 1:1 conversion tool
- A GML to GDScript transpiler *(yet)*
- A tool for converting compiled GM projects (use [UndertaleToolMod](https://github.com/UnderminersTeam/UndertaleModTool) instead)

## Releases
Downloadable releases can be found on the side of this page, for now executables are only available on Windows but we will work on other platforms too

## Installation

1. **Clone the Repository**
```bash
git clone https://github.com/Infiland/GM2Godot
cd GM2Godot
```

2. **Install Python Requirements**
- Requires Python 3.9.0 or later
- Install required packages:
```bash
pip install Pillow markdown2 tkhtmlview
```

3. **Additional Requirements**
- For Linux users (Ubuntu/Debian):
```bash
sudo apt-get install python3-tk python3-pil python3-pil.imagetk python3-markdown2
```
Note: If tkhtmlview installation fails, try:
```bash
pip install tkhtmlview --break-system-packages
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
