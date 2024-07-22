# GM2Godot

GM2Godot is a tool which converts GameMaker (2024.6.2) projects to Godot (4.2) projects.
This repository is work in progress and I'll slowly add Contributing.MD, issues, branches and milestones.
Feel free to help!

# What it is and what it isn't

When presenting this tool, I've gotten a couple of questions what the tool really is and what it is supposed to be, so I'll break it down.

**GM2Godot is:**
- A tool that ports assets from GameMaker to Godot
- Is for people who don't want to port the GameMaker project to Godot from scratch
- Not perfect. It will make mistakes.

**GM2Godot isn't:**
- For people who expect everything will work perfectly.
- A compiler that can seemingly translate GML to GDScript
- This isn't a tool which converts exported GML projects to Godot, [use UndertaleToolMod instead](https://github.com/UnderminersTeam/UndertaleModTool)

# Contribution
I will make contributing.md later! But pretty much do pull requests and I'll try to code review them.

# Installation

Clone this repository
```
git clone https://github.com/Infiland/GM2Godot
```
Open VSC and install Python 3.12.0 or later (I haven't tested older python versions)
```
py --version
```
You can download [python here.](https://www.python.org/downloads/)

If you are Linux, **you are required to have Tkinter module**, do the following: (tested this on Ubuntu, so it probably works on debian based systems)
```
sudo apt-get install python3-tk python3-pil python3-pil.imagetk
```

The program requires the Pillow library to use
```
pip install Pillow
```
Once installed, you can run the program:
```
python main.py
```

# How to use
The tool will open a GUI menu upon running main.py.

At the top, place the GameMaker directory and the Godot directory in each textbox.
NOTE: Godot directory needs to be completely empty to avoid data loss, GameMaker should stay as is.

Once you put both directories in the tool, it will start taking assets from GameMaker and port them into your empty Godot project.
The tool will be done when it says so in the console and when the progress bar is at 100%.