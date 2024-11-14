import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
import platform
import os
import requests
import webbrowser
from PIL import Image, ImageTk
from io import BytesIO
from datetime import datetime

VERSION = "0.0.11"

def get_version():
    """Return the current version of the application."""
    return VERSION

class ModernButton(ttk.Button):
    """A styled button with modern appearance."""
    def __init__(self, master=None, **kw):
        super().__init__(master, style="Modern.TButton", **kw)

class ModernProgressBar(tk.Canvas):
    """A custom progress bar with modern styling."""
    def __init__(self, master, width, height, bg_color, fill_color, text_color):
        super().__init__(master, width=width, height=height, bg=bg_color, highlightthickness=0)
        self.fill_color = fill_color
        self.text_color = text_color
        self.width = width
        self.height = height
        self.progress = 0
        self.rect_id = self.create_rectangle(0, width, 0, height, fill=fill_color)
        self.text_id = self.create_text(width // 2, height // 2, text="0%", fill=text_color, font=("Helvetica", 12, "bold"))

    def update_progress(self, value):
        """Update the progress bar to show the current progress."""
        self.progress = value
        fill_width = int(self.width * (value / 100))
        self.coords(self.rect_id, 0, 0, fill_width, self.height)
        self.itemconfig(self.text_id, text=f"{value}%")
        self.lift(self.text_id)
        self.update_idletasks()

class Icon:
    """Manages application icons and their loading."""
    def __init__(self, master):
        self.master = master
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.set_program_icon()
        self.gm_icon = self.load_icon("img/Gamemaker.png")
        self.godot_icon = self.load_icon("img/Godot.png")
    
    def set_program_icon(self):
        """Set the program's main icon based on the operating system."""
        icon_path = os.path.join(self.base_path, "img", "Logo.png")
        icon_setters = {
            "Windows": self.set_windows_icon,
            "Linux": self.set_linux_icon
        }
        icon_setter = icon_setters.get(platform.system(), self.set_default_icon)
        icon_setter(icon_path)

    def set_windows_icon(self, icon_path):
        """Set icon for Windows platform."""
        try:
            icon = tk.PhotoImage(file=icon_path)
            self.master.iconphoto(False, icon)
        except Exception as e:
            print(f"Failed to set icon using PhotoImage: {e}")
            self.set_default_icon(icon_path)

    def set_linux_icon(self, icon_path):
        """Set icon for Linux platform."""
        try:
            img = tk.Image("photo", file=icon_path)
            self.master.tk.call('wm', 'iconphoto', self.master._w, img)
        except Exception as e:
            print(f"Failed to set icon on Linux: {e}")
            self.set_default_icon(icon_path)

    def set_default_icon(self, icon_path):
        """Set default icon as fallback."""
        try:
            icon = tk.PhotoImage(file=icon_path)
            self.master.iconphoto(True, icon)
        except tk.TclError:
            print(f"Failed to load icon from {icon_path}. The icon will not be displayed.")

    def load_icon(self, path):
        """Load an icon from the specified path."""
        try:
            full_path = os.path.join(self.base_path, path)
            img = Image.open(full_path)
            return ImageTk.PhotoImage(img.resize((20, 20), Image.Resampling.LANCZOS))
        except Exception as e:
            print(f"Failed to load icon from {full_path}: {e}")
            return None
        
    def get_gamemaker_icon(self):
        """Get the GameMaker icon."""
        return self.gm_icon
    
    def get_godot_icon(self):
        """Get the Godot icon."""
        return self.godot_icon
    
class AboutDialog:
    """About dialog showing application information and contributors."""
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About GM2Godot")
        self.dialog.geometry("600x700")
        self.dialog.configure(bg="#222222")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self.style = ttk.Style()
        self.setup_styles()
        self.create_widgets()
        
    def setup_styles(self):
        """Configure styles for the About dialog."""
        styles = {
            "About.TFrame": {"background": "#222222"},
            "About.TLabel": {
                "background": "#222222",
                "foreground": "#ffffff",
                "font": ('Helvetica', 10)
            },
            "AboutTitle.TLabel": {
                "background": "#222222",
                "foreground": "#ffffff",
                "font": ('Helvetica', 16, 'bold')
            },
            "AboutSection.TLabel": {
                "background": "#222222",
                "foreground": "#ffffff",
                "font": ('Helvetica', 12, 'bold')
            }
        }
        for style, options in styles.items():
            self.style.configure(style, **options)
                           
    def create_widgets(self):
        """Create and layout all widgets in the About dialog."""
        main_frame = ttk.Frame(self.dialog, style="About.TFrame", padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, 
                 text=f"GM2Godot v{get_version()}", 
                 style="AboutTitle.TLabel").pack(pady=(0, 10))
        
        description = (
            "GM2Godot is a tool designed to help developers migrate their "
            "GameMaker projects to the Godot Engine. It automates the conversion "
            "of various project assets and settings, making the transition smoother."
        )
        ttk.Label(main_frame, 
                 text=description, 
                 style="About.TLabel", 
                 wraplength=500).pack(pady=(0, 20))
        
        ttk.Label(main_frame, 
                 text="Contributors", 
                 style="AboutSection.TLabel").pack(pady=(0, 10))
        
        self.create_contributors_list(main_frame)
        self.create_links_section(main_frame)
        self.create_copyright_label(main_frame)
    
    def create_contributors_list(self, parent):
        """Create scrollable contributors list."""
        contributors_frame = ttk.Frame(parent, style="About.TFrame")
        contributors_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(contributors_frame, 
                         bg="#222222", 
                         highlightthickness=0)
        scrollbar = ttk.Scrollbar(contributors_frame, 
                                orient="vertical", 
                                command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style="About.TFrame")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), 
                           window=scrollable_frame, 
                           anchor="nw", 
                           width=500)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.display_contributors(scrollable_frame)
    
    def create_links_section(self, parent):
        """Create links section with clickable links."""
        links_frame = ttk.Frame(parent, style="About.TFrame")
        links_frame.pack(pady=20)
        
        links = [
            ("GitHub Repository", "https://github.com/Infiland/GM2Godot"),
            ("Report an Issue", "https://github.com/Infiland/GM2Godot/issues"),
            ("Infiland Website", "https://infiland.github.io")
        ]
        
        for text, url in links:
            link = ttk.Label(links_frame, 
                           text=text,
                           style="About.TLabel",
                           cursor="hand2")
            link.pack(pady=2)
            link.bind("<Button-1>", lambda e, url=url: webbrowser.open_new(url))
    
    def create_copyright_label(self, parent):
        """Create copyright label with current year."""
        current_year = datetime.now().year
        copyright_text = f"© {current_year} Infiland. All rights reserved."
        ttk.Label(parent, 
                 text=copyright_text,
                 style="About.TLabel").pack(pady=(20, 0))
                 
    def display_contributors(self, parent_frame):
        """Fetch and display GitHub contributors."""
        try:
            response = requests.get(
                "https://api.github.com/repos/Infiland/GM2Godot/contributors",
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            response.raise_for_status()
            contributors = response.json()
            
            for contributor in contributors:
                self.create_contributor_widget(parent_frame, contributor)
                
        except Exception as e:
            ttk.Label(parent_frame,
                     text=f"Failed to load contributors: {str(e)}",
                     style="About.TLabel").pack(pady=5)
                     
    def create_contributor_widget(self, parent_frame, contributor):
        """Create a widget for a single contributor."""
        contributor_frame = ttk.Frame(parent_frame, style="About.TFrame")
        contributor_frame.pack(fill=tk.X, pady=5, padx=5)
        
        try:
            response = requests.get(contributor['avatar_url'])
            image = Image.open(BytesIO(response.content))
            image = image.resize((40, 40), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            
            avatar_label = ttk.Label(contributor_frame, 
                                   image=photo, 
                                   style="About.TLabel")
            avatar_label.image = photo  # Keep a reference
            avatar_label.pack(side=tk.LEFT, padx=(0, 10))
        except:
            pass
            
        info_frame = ttk.Frame(contributor_frame, style="About.TFrame")
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        name_label = ttk.Label(info_frame,
                             text=contributor['login'],
                             style="About.TLabel",
                             cursor="hand2")
        name_label.pack(anchor="w")
        name_label.bind("<Button-1>", 
                       lambda e, url=contributor['html_url']: webbrowser.open_new(url))
        
        contributions = f"{contributor['contributions']} contributions"
        ttk.Label(info_frame,
                 text=contributions,
                 style="About.TLabel").pack(anchor="w")
        
class SetupUI:
    """Main UI setup for the application."""
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
        """Initialize the main UI layout."""
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
        """Create input fields for project paths."""
        paths = [
            ("GameMaker", self.app.browse_gm, self.icon.get_gamemaker_icon()), 
            ("Godot", self.app.browse_godot, self.icon.get_godot_icon())
        ]
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
        """Create main action buttons."""
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
        """Get a button by its name."""
        return self.buttons.get(button_name.lower())

    def create_console(self, parent):
        """Create the console output area."""
        console_frame = ttk.Frame(parent, style="TFrame")
        console_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        parent.rowconfigure(3, weight=1)

        self.console = tk.Text(console_frame, wrap=tk.WORD, height=15, bg="#3d3d3d", 
                             fg="#ffffff", insertbackground="#ffffff", 
                             font=('Consolas', 10), state='disabled')
        self.console.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", 
                                command=self.console.yview, 
                                style="Console.Vertical.TScrollbar")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console.configure(yscrollcommand=scrollbar.set)

    def create_progress_bar(self, parent):
        """Create the progress bar and related labels."""
        progress_frame = ttk.Frame(parent, style="TFrame")
        progress_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        self.progress = ModernProgressBar(progress_frame, width=500, height=30, 
                                        bg_color="#3d3d3d", fill_color="#42ffc2", 
                                        text_color="#ffffff")
        self.progress.pack(side=tk.LEFT, expand=True)

        self.timer_label = ttk.Label(parent, text="Time: 00:00:00", style="TLabel")
        self.timer_label.grid(row=5, column=0, columnspan=3, pady=(0, 10))

        self.status_label = ttk.Label(parent, text="", foreground="#ffffff", style="TLabel")
        self.status_label.grid(row=5, column=0, columnspan=3, pady=(0, 10), padx=(0, 400))

    def create_info_labels(self, parent):
        """Create informational labels and links."""
        info_frame = ttk.Frame(parent, style="TFrame")
        info_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        labels = [
            (f"Version {get_version()}", self.app.show_release_notes, tk.LEFT),
            ("About", self.app.show_about, tk.LEFT),
            ("Contribute", self.app.open_github, tk.LEFT),
            ("Made by Infiland", self.app.open_infiland_website, tk.RIGHT)
        ]

        for text, command, side in labels:
            label = ttk.Label(info_frame, text=text, style="TLabel", cursor="hand2")
            label.pack(side=side, padx=10)
            label.bind("<Button-1>", command)