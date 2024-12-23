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
        main_frame = ttk.Frame(self.master, padding="40 40 40 40", style="TFrame")
        main_frame.grid(column=0, row=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.create_project_path_inputs(main_frame)
        self.create_buttons(main_frame)
        self.create_console(main_frame)
        self.create_progress_bar(main_frame)
        self.create_info_labels(main_frame)

    def create_project_path_inputs(self, parent):
        paths = [("GameMaker", self.app.browse_gm, self.icon.get_gamemaker_icon()), 
                ("Godot", self.app.browse_godot, self.icon.get_godot_icon())]
                
        for idx, (label, command, icon) in enumerate(paths):
            frame = ttk.Frame(parent, style="TFrame")
            frame.grid(row=idx, column=0, sticky=tk.W, padx=5, pady=(0, 20))
            
            icon_label = ttk.Label(frame, text=label[:2] if icon is None else "", image=icon, style="TLabel")
            icon_label.pack(side=tk.LEFT, padx=(0, 10))
            
            path_label = ttk.Label(frame, text=f"{label} Project Path:", style="TLabel")
            path_label.pack(side=tk.LEFT)
            
            entry = ttk.Entry(parent, width=50, style="TEntry")
            entry.grid(row=idx, column=1, padx=10, pady=(0, 20), sticky=(tk.W, tk.E))
            
            browse_button = ModernButton(parent, text=f"Browse {label}", command=command)
            browse_button.grid(row=idx, column=2, padx=5, pady=(0, 20))
            
            self.entries[label.lower()] = entry
            
        parent.columnconfigure(1, weight=1)

    def create_buttons(self, parent):
        button_frame = ttk.Frame(parent, style="TFrame")
        button_frame.grid(row=2, column=0, columnspan=3, pady=(0, 30))

        # Create convert and settings buttons
        convert_button = ModernButton(button_frame, text="Convert", command=self.app.start_conversion)
        convert_button.grid(row=0, column=0, padx=10)
        self.buttons["convert"] = convert_button

        # Create stop button with icon
        stop_button = ModernButton(button_frame, command=self.app.stop_conversion, state=tk.DISABLED, icon_only=True)
        stop_icon = ModernButton.create_stop_icon(button_frame, size=24)
        stop_button.configure(image=stop_icon)
        stop_button._icon = stop_icon  # Keep a reference to prevent garbage collection
        stop_button.grid(row=0, column=1, padx=10)
        self.buttons["stop"] = stop_button

        settings_button = ModernButton(button_frame, text="Settings", command=self.app.open_settings)
        settings_button.grid(row=0, column=2, padx=10)
        self.buttons["settings"] = settings_button

    def get_button(self, button_name):
        return self.buttons.get(button_name.lower())

    def create_console(self, parent):
        console_frame = ttk.Frame(parent, style="TFrame")
        console_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        parent.rowconfigure(3, weight=1)

        self.console = tk.Text(console_frame, 
                             wrap=tk.WORD, 
                             height=15, 
                             bg="#2d2d2d", 
                             fg="#e0e0e0", 
                             insertbackground="#e0e0e0", 
                             font=('Cascadia Code', 10), 
                             state='disabled',
                             padx=10,
                             pady=10,
                             relief="flat",
                             borderwidth=0)
        self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(console_frame, 
                                orient="vertical", 
                                command=self.console.yview, 
                                style="Console.Vertical.TScrollbar")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console.configure(yscrollcommand=scrollbar.set)

    def create_progress_bar(self, parent):
        progress_frame = ttk.Frame(parent, style="TFrame")
        progress_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))

        self.progress = ModernProgressBar(progress_frame, 
                                        width=500, 
                                        height=30, 
                                        bg_color="#2d2d2d", 
                                        fill_color="#0078d4", 
                                        text_color="#ffffff")
        self.progress.pack(side=tk.LEFT, expand=True, fill=tk.X)

        status_frame = ttk.Frame(parent, style="TFrame")
        status_frame.grid(row=5, column=0, columnspan=3, pady=(0, 20))
        
        self.timer_label = ttk.Label(status_frame, 
                                   text="Time: 00:00:00", 
                                   style="TLabel",
                                   font=('Segoe UI', 10))
        self.timer_label.pack(side=tk.LEFT, padx=(0, 20))

        self.status_label = ttk.Label(status_frame, 
                                    text="", 
                                    style="TLabel",
                                    font=('Segoe UI', 10))
        self.status_label.pack(side=tk.LEFT)

    def create_info_labels(self, parent):
        info_frame = ttk.Frame(parent, style="TFrame")
        info_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 0))

        labels = [
            (f"Version {get_version()}", self.app.show_release_notes, tk.LEFT),
            ("Contribute", self.app.open_github, tk.LEFT),
            ("Made by Infiland", self.app.open_infiland_website, tk.RIGHT)
        ]

        for text, command, side in labels:
            label = ttk.Label(info_frame, 
                            text=text, 
                            style="TLabel", 
                            cursor="hand2",
                            font=('Segoe UI', 9))
            label.pack(side=side, padx=10)
            label.bind("<Button-1>", command)
            label.bind('<Enter>', lambda e, label=label: label.configure(foreground="#0078d4"))
            label.bind('<Leave>', lambda e, label=label: label.configure(foreground="#e0e0e0"))