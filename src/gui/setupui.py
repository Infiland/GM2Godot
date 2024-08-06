import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

from src.gui.modern_progress_bar import ModernProgressBar
from src.gui.modern_button import ModernButton
from src.gui.icon import Icon

from src.version import get_version

class SetupUI:
    def __init__(self, master, app):
        self.master = master
        self.app = app
        self.icon = Icon(self.master)
        self.entries = {}
        self.buttons = {}
        self.progress = None
        self.console = None
        self.timer_label = None
        self.status_label = None

    def setup_ui(self):
        main_frame = ttk.Frame(self.master, padding="20 20 20 20", style="TFrame")
        main_frame.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.create_project_path_inputs(main_frame)
        self.create_buttons(main_frame)
        self.create_console(main_frame)
        self.create_progress_bar(main_frame)
        self.create_info_labels(main_frame)

    def create_project_path_inputs(self, parent):
        paths = [("GameMaker", self.app.browse_gm, self.icon.get_gamemaker_icon()), ("Godot", self.app.browse_godot, self.icon.get_godot_icon())]
        for idx, (label, command, icon) in enumerate(paths):
            frame = ttk.Frame(parent, style="TFrame")
            frame.grid(row=idx, column=0, sticky=tk.W, padx=5, pady=5)
            
            ttk.Label(frame, text=label[:2] if icon is None else "", image=icon, style="TLabel").pack(side=tk.LEFT, padx=(0, 5))
            ttk.Label(frame, text=f"{label} Project Path:", style="TLabel").pack(side=tk.LEFT)
            
            entry = ttk.Entry(parent, width=50, style="TEntry")
            entry.grid(row=idx, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
            ModernButton(parent, text=f"Browse {label} Path", command=command).grid(row=idx, column=2, padx=5, pady=5)
            self.entries[label.lower()] = entry
        parent.columnconfigure(1, weight=1)

    def create_buttons(self, parent):
        button_frame = ttk.Frame(parent, style="TFrame")
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)

        buttons = [
            ("Convert", self.app.start_conversion, tk.NORMAL),
            ("Stop", self.app.stop_conversion, tk.DISABLED),
            ("Settings", self.app.open_settings, tk.NORMAL)
        ]

        for idx, (text, command, state) in enumerate(buttons):
            button = ModernButton(button_frame, text=text, command=command, state=state)
            button.grid(row=0, column=idx, padx=5, pady=10)
            self.buttons[text.lower()] = button

        self.buttons["stop"].configure(style="Red.TButton")

    def get_button(self, button_name):
        return self.buttons.get(button_name.lower())

    def create_console(self, parent):
        console_frame = ttk.Frame(parent, style="TFrame")
        console_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        parent.rowconfigure(3, weight=1)

        self.console = tk.Text(console_frame, wrap=tk.WORD, height=15, bg="#3d3d3d", fg="#ffffff", insertbackground="#ffffff", font=('Consolas', 10), state='disabled')
        self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview, style="Console.Vertical.TScrollbar")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console.configure(yscrollcommand=scrollbar.set)

    def create_progress_bar(self, parent):
        progress_frame = ttk.Frame(parent, style="TFrame")
        progress_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        self.progress = ModernProgressBar(progress_frame, width=500, height=30, bg_color="#3d3d3d", fill_color="#42ffc2", text_color="#ffffff")
        self.progress.pack(side=tk.LEFT, expand=True)

        self.timer_label = ttk.Label(parent, text="Time: 00:00:00", style="TLabel")
        self.timer_label.grid(row=5, column=0, columnspan=3, pady=(0, 10))

        self.status_label = ttk.Label(parent, text="", foreground="#ffffff", style="TLabel")
        self.status_label.grid(row=5, column=0, columnspan=3, pady=(0, 10), padx=(0, 400))

    def create_info_labels(self, parent):
        info_frame = ttk.Frame(parent, style="TFrame")
        info_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        labels = [
            (f"Version {get_version()}", self.app.show_release_notes, tk.LEFT),
            ("Contribute", self.app.open_github, tk.LEFT),
            ("Made by Infiland", self.app.open_infiland_website, tk.RIGHT)
        ]

        for text, command, side in labels:
            label = ttk.Label(info_frame, text=text, style="TLabel", cursor="hand2")
            label.pack(side=side, padx=10)
            label.bind("<Button-1>", command)