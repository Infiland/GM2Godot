import os
import threading
import time
import webbrowser
from functools import partial
import requests
import markdown2
import platform
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont
from tkhtmlview import HTMLLabel

from sprites import SpriteConverter
from sounds import SoundConverter
from fonts import FontConverter
from notes import NoteConverter
from tilesets import TileSetConverter
from project_settings import ProjectSettingsConverter

class ModernButton(ttk.Button):
    def __init__(self, master=None, **kw):
        super().__init__(master, style="Modern.TButton", **kw)

class CoolProgressBar(tk.Canvas):
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
        self.progress = value
        fill_width = int(self.width * (value / 100))
        self.coords(self.rect_id, 0, 0, fill_width, self.height)
        self.itemconfig(self.text_id, text=f"{value}%")
        self.lift(self.text_id)
        self.update_idletasks()

class ConverterGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("GM2Godot")
        self.master.geometry("800x600")
        self.master.configure(bg="#222222")
        self.set_program_icon()

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.setup_styles()

        self.gm_icon = self.load_icon("img/Gamemaker.png")
        self.godot_icon = self.load_icon("img/Godot.png")

        self.setup_ui()
        self.setup_conversion_settings()
        self.conversion_running = threading.Event()
        self.conversion_thread = None
        self.timer_running = False
        self.start_time = 0
    
    def set_program_icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), "img", "Logo.png")
        icon_setters = {
            "Windows": self.set_windows_icon,
            "Linux": self.set_linux_icon
        }
        icon_setter = icon_setters.get(platform.system(), self.set_default_icon)
        icon_setter(icon_path)

    def set_windows_icon(self, icon_path):
        try:
            icon = tk.PhotoImage(file=icon_path)
            self.master.iconphoto(False, icon)
            print(f"Icon set successfully using PhotoImage: {icon_path}")
        except Exception as e:
            print(f"Failed to set icon using PhotoImage: {e}")
            self.set_default_icon(icon_path)

    def set_linux_icon(self, icon_path):
        try:
            img = tk.Image("photo", file=icon_path)
            self.master.tk.call('wm', 'iconphoto', self.master._w, img)
        except Exception as e:
            print(f"Failed to set icon on Linux: {e}")
            self.set_default_icon(icon_path)

    def set_default_icon(self, icon_path):
        try:
            icon = tk.PhotoImage(file=icon_path)
            self.master.iconphoto(True, icon)
        except tk.TclError:
            print(f"Failed to load icon from {icon_path}. The icon will not be displayed.")

    def load_icon(self, path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            return ImageTk.PhotoImage(img.resize((20, 20), Image.Resampling.LANCZOS))
        except Exception:
            return None

    def setup_styles(self):
        styles = {
            "TFrame": {"background": "#222222"},
            "TLabel": {"background": "#222222", "foreground": "#ffffff", "font": ('Helvetica', 10)},
            "TEntry": {"fieldbackground": "#3d3d3d", "foreground": "#ffffff", "insertcolor": "#ffffff", "font": ('Helvetica', 10)},
            "Modern.TButton": {"background": "#abc9ff", "foreground": "#222222", "font": ('Helvetica', 10, 'bold'), "padding": (10, 5)},
            "TCheckbutton": {"background": "#222222", "foreground": "#ffffff"},
            "Console.Vertical.TScrollbar": {"background": "#3d3d3d", "troughcolor": "#222222", "arrowcolor": "#ffffff"},
            "Red.TButton": {"background": "red", "foreground": "white"}
        }
        for style, options in styles.items():
            self.style.configure(style, **options)

        self.style.map("TEntry", fieldbackground=[('readonly', '#3d3d3d')])
        self.style.map("Modern.TButton", background=[('active', '#9ab8ee'), ('disabled', '#666666')], foreground=[('disabled', '#aaaaaa')])
        self.style.map("TCheckbutton", background=[('active', '#222222')])
        self.style.map("Red.TButton", background=[('active', '#ff6666')])
        self.style.configure("Red.TButton", background="white", foreground="white")

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
        paths = [("GameMaker", self.browse_gm, self.gm_icon), ("Godot", self.browse_godot, self.godot_icon)]
        for idx, (label, command, icon) in enumerate(paths):
            frame = ttk.Frame(parent, style="TFrame")
            frame.grid(row=idx, column=0, sticky=tk.W, padx=5, pady=5)
            
            ttk.Label(frame, text=label[:2] if icon is None else "", image=icon, style="TLabel").pack(side=tk.LEFT, padx=(0, 5))
            ttk.Label(frame, text=f"{label} Project Path:", style="TLabel").pack(side=tk.LEFT)
            
            entry = ttk.Entry(parent, width=50, style="TEntry")
            entry.grid(row=idx, column=1, padx=5, pady=5, sticky=(tk.W, tk.E))
            ModernButton(parent, text=f"Browse {label} Path", command=command).grid(row=idx, column=2, padx=5, pady=5)
            setattr(self, f"{label.lower()}_entry", entry)
        parent.columnconfigure(1, weight=1)

    def create_buttons(self, parent):
        button_frame = ttk.Frame(parent, style="TFrame")
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)

        buttons = [
            ("Convert", self.start_conversion, tk.NORMAL),
            ("Stop", self.stop_conversion, tk.DISABLED),
            ("Settings", self.open_settings, tk.NORMAL)
        ]

        for idx, (text, command, state) in enumerate(buttons):
            button = ModernButton(button_frame, text=text, command=command, state=state)
            button.grid(row=0, column=idx, padx=5, pady=10)
            setattr(self, f"{text.lower()}_button", button)

        self.stop_button.configure(style="Red.TButton")

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

        self.progress = CoolProgressBar(progress_frame, width=500, height=30, bg_color="#3d3d3d", fill_color="#42ffc2", text_color="#ffffff")
        self.progress.pack(side=tk.LEFT, expand=True)

        self.timer_label = ttk.Label(parent, text="Time: 00:00:00", style="TLabel")
        self.timer_label.grid(row=5, column=0, columnspan=3, pady=(0, 10))

        self.status_label = ttk.Label(parent, text="", foreground="#ffffff", style="TLabel")
        self.status_label.grid(row=5, column=0, columnspan=3, pady=(0, 10),padx=(0,400))

    def create_info_labels(self, parent):
        info_frame = ttk.Frame(parent, style="TFrame")
        info_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        labels = [
            ("Version 0.0.9", self.show_release_notes, tk.LEFT),
            ("Contribute", self.open_github, tk.LEFT),
            ("Made by Infiland", self.open_infiland_website, tk.RIGHT)
        ]

        for text, command, side in labels:
            label = ttk.Label(info_frame, text=text, style="TLabel", cursor="hand2")
            label.pack(side=side, padx=10)
            label.bind("<Button-1>", command)

    def show_release_notes(self, event):
        release_notes = self.fetch_release_notes()
        if release_notes:
            self.display_release_notes(release_notes)
        else:
            messagebox.showerror("Error", "Unable to fetch release notes. Please check your internet connection and try again.")

    def fetch_release_notes(self):
        try:
            response = requests.get("https://api.github.com/repos/Infiland/GM2Godot/releases/latest")
            if response.status_code == 200:
                return response.json()['body']
            else:
                return None
        except Exception as e:
            print(f"Error fetching release notes: {e}")
            return None

    def display_release_notes(self, notes):
        notes_window = tk.Toplevel(self.master)
        notes_window.title("Release Notes")
        notes_window.geometry("750x600")
        notes_window.configure(bg="#222222")

        html_content = markdown2.markdown(notes)

        text_widget = tk.Text(notes_window, wrap=tk.WORD, bg="#3d3d3d", fg="#ffffff", font=("Arial", 11), padx=10, pady=10)
        text_widget.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

        scrollbar = ttk.Scrollbar(text_widget, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.tag_configure("h1", font=("Arial", 16, "bold"), spacing3=5)
        text_widget.tag_configure("h2", font=("Arial", 14, "bold"), spacing3=5)
        text_widget.tag_configure("bullet", lmargin1=20, lmargin2=30)
        text_widget.tag_configure("link", foreground="#4da6ff", underline=True)

        def insert_formatted(content):
            for line in content.split('\n'):
                if line.startswith('<h1>'):
                    text_widget.insert(tk.END, line[4:-5] + '\n', "h1")
                elif line.startswith('<h2>'):
                    text_widget.insert(tk.END, line[4:-5] + '\n', "h2")
                elif line.startswith('<ul>'):
                    text_widget.insert(tk.END, line[4:-5] + '\n', "ul")
                elif line.startswith('<strong>'):
                    text_widget.insert(tk.END, line[4:-5] + '\n', "strong")
                elif line.startswith('<li>'):
                    text_widget.insert(tk.END, "• " + line[4:-5] + '\n', "bullet")
                elif line.startswith('<p>'):
                    text_widget.insert(tk.END, line[3:-4] + '\n\n')
                elif line.startswith('<a href='): # This doesn't work :(
                    start = line.find('"') + 1
                    end = line.find('"', start)
                    url = line[start:end]
                    text = line[line.find('>')+1:line.find('</a>')]
                    text_widget.insert(tk.END, text, "link")
                    text_widget.tag_bind("link", "<Button-1>", lambda e, url=url: webbrowser.open_new(url))
                else:
                    text_widget.insert(tk.END, line + '\n')

        insert_formatted(html_content)

        text_widget.configure(state="disabled")

    def setup_conversion_settings(self):
        settings = [
            "sprites", "sounds", "fonts", "tilesets", "objects", "notes", "shaders",
            "game_icon", "project_settings", "project_name", "audio_buses"
        ]
        self.conversion_settings = {setting: tk.BooleanVar(value=True) for setting in settings}
        self.conversion_settings["notes"].set(False)
        self.conversion_settings["objects"].set(False)
        
    def open_settings(self):
        settings_window = tk.Toplevel(self.master)
        settings_window.title("Conversion Settings")
        settings_window.geometry("400x500")
        settings_window.configure(bg="#222222")

        main_frame = ttk.Frame(settings_window, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select files to convert:", style="TLabel", font=("Helvetica", 14, "bold")).pack(pady=10)

        checkbox_frame = ttk.Frame(main_frame, style="TFrame")
        checkbox_frame.pack(fill=tk.BOTH, expand=True)

        categories = {
            "Assets": ["sprites", "sounds", "fonts"],
            "Project": ["game_icon", "project_settings", "project_name", "audio_buses", "notes"],
            "WIP": ["objects", "shaders", "tilesets"]
        }

        row = 0
        for category, settings in categories.items():
            ttk.Label(checkbox_frame, text=category, style="TLabel", font=("Helvetica", 12, "bold")).grid(row=row, column=0, sticky="w", pady=(10, 5))
            row += 1
            for setting in settings:
                var = self.conversion_settings[setting]
                ttk.Checkbutton(checkbox_frame, text=setting.replace("_", " ").title(), variable=var, style="TCheckbutton").grid(row=row, column=0, sticky="w", padx=20)
                row += 1

        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=10)

        def select_all():
            for var in self.conversion_settings.values():
                var.set(True)

        def deselect_all():
            for var in self.conversion_settings.values():
                var.set(False)

        ModernButton(button_frame, text="Select All", command=select_all).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text="Deselect All", command=deselect_all).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text="Save", command=settings_window.destroy).pack(side=tk.LEFT, padx=5)

    def log(self, message):
        self.console.configure(state='normal')
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)
        self.console.configure(state='disabled')

    def browse_project(self, entry, file_check, dialog_title):
        folder = filedialog.askdirectory(title=dialog_title)
        if folder:
            entry.delete(0, tk.END)
            entry.insert(0, folder)
            file_check(folder)

    def browse_gm(self):
        self.browse_project(self.gamemaker_entry, self.check_gm_project, "Select your GameMaker Project")

    def browse_godot(self):
        self.browse_project(self.godot_entry, self.check_godot_project, "Select your new Godot project")

    def check_project_file(self, folder, file_extension, file_name):
        files = [f for f in os.listdir(folder) if f.endswith(file_extension)]
        if not files:
            messagebox.showwarning(f"Invalid {file_name} Project", f"No {file_extension} file found in the selected {file_name} project folder.")
        elif len(files) > 1:
            messagebox.showwarning(f"Multiple {file_extension} Files", f"Multiple {file_extension} files found: {', '.join(files)}. Please ensure only one {file_extension} file is present.")
        else:
            self.log(f"{file_name} project file found: {files[0]}")

    def check_gm_project(self, folder):
        self.check_project_file(folder, '.yyp', 'GameMaker')

    def check_godot_project(self, folder):
        self.check_project_file(folder, 'project.godot', 'Godot')

    def update_progress(self, value):
        self.progress['value'] = value
        self.progress_label.config(text=f"{value}%")

    def start_conversion(self):
        gm_path, godot_path = self.gamemaker_entry.get(), self.godot_entry.get()
        if not gm_path or not godot_path:
            self.log("Please select both GameMaker and Godot project paths.")
            return

        if not self.validate_projects(gm_path, godot_path):
            return

        self.prepare_for_conversion()
        self.conversion_thread = threading.Thread(target=self.convert, args=(gm_path, godot_path))
        self.conversion_thread.start()
        self.start_timer()
        self.style.configure("Red.TButton", background="red", foreground="white")
        self.stop_button.config(state=tk.NORMAL, style="Red.TButton")

    def validate_projects(self, gm_path, godot_path):
        yyp_files = [f for f in os.listdir(gm_path) if f.endswith('.yyp')]
        godot_project_file = os.path.join(godot_path, 'project.godot')

        if not yyp_files or len(yyp_files) > 1 or not os.path.exists(godot_project_file):
            self.log_project_errors(yyp_files, godot_project_file)
            return False
        return True

    def log_project_errors(self, yyp_files, godot_project_file):
        if not yyp_files:
            self.log("Error: No .yyp file found in the GameMaker project folder.")
        elif len(yyp_files) > 1:
            self.log(f"Warning: Multiple .yyp files found: {', '.join(yyp_files)}. Using the first one.")
        if not os.path.exists(godot_project_file):
            self.log("Error: No project.godot file found in the Godot project folder.")

    def prepare_for_conversion(self):
        self.convert_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.conversion_running.set()
        self.console.delete('1.0', tk.END)
        self.progress.update_progress(0)
        self.log("Starting conversion...")

    def stop_conversion(self):
        if self.conversion_running.is_set():
            self.conversion_running.clear()
            self.log("Stopping conversion process...")
            self.style.configure("Red.TButton", background="white", foreground="white")
            self.stop_button.config(state=tk.DISABLED, style="TButton")
            self.master.after(100, self.check_conversion_stopped)

    def start_timer(self):
        self.timer_running = True
        self.start_time = time.time()
        self.update_timer()

    def stop_timer(self):
        self.timer_running = False

    def update_timer(self):
        if self.timer_running:
            elapsed_time = int(time.time() - self.start_time)
            hours, remainder = divmod(elapsed_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_str = f"Time: {hours:02d}:{minutes:02d}:{seconds:02d}"
            self.timer_label.config(text=time_str)
            self.master.after(1000, self.update_timer)

    def convert(self, gm_path, godot_path):
        project_settings_converter = ProjectSettingsConverter(gm_path, godot_path, self.threadsafe_log)

        converters = [
            ("game_icon", project_settings_converter.convert_icon, "Converting game icon..."),
            ("project_name", project_settings_converter.update_project_name, "Updating project name..."),
            ("project_settings", project_settings_converter.update_project_settings, "Updating project settings..."),
            ("audio_buses", project_settings_converter.generate_audio_bus_layout, "Generating audio bus layout..."),
            ("sprites", lambda: SpriteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), "Converting sprites..."),
            ("fonts", lambda: FontConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), "Converting fonts..."),
            ("tilesets", lambda: TileSetConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), "Converting tilesets..."),
            ("sounds", lambda: SoundConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_sounds(), "Converting sounds..."),
            ("notes", lambda: NoteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), "Converting notes...")
        ]

        for setting, converter, log_message in converters:
            if self.conversion_settings[setting].get() and self.conversion_running.is_set():
                self.threadsafe_log(log_message)
                self.threadsafe_update_status(log_message)
                converter()
                self.threadsafe_update_progress(0)

        self.master.after(0, self.conversion_complete)

    def check_conversion_stopped(self):
        if self.conversion_thread and self.conversion_thread.is_alive():
            self.master.after(100, self.check_conversion_stopped)
        else:
            self.conversion_complete()

    def threadsafe_log(self, message):
        self.master.after(0, self.log, message)

    def threadsafe_update_status(self, message):
        self.master.after(0, self.status_label.config, {"text": message})

    def threadsafe_update_progress(self, value):
        self.master.after(0, self.progress.update_progress, value)

    def conversion_complete(self):
        self.progress.update_progress(100)
        self.status_label.config(text="Conversion complete!")
        self.log("You have ported your project from GameMaker to Godot! Have fun!" if self.conversion_running.is_set() else "Conversion process stopped.")
        self.conversion_running.clear()
        self.convert_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.stop_timer()

    def open_github(self, event):
        webbrowser.open_new("https://github.com/Infiland/GM2Godot")

    def open_infiland_website(self, event):
        webbrowser.open_new("https://infiland.github.io")

def main():
    root = tk.Tk()
    ConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()