import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk, messagebox
from sprites import SpriteConverter
from sounds import SoundConverter
from fonts import FontConverter
from tilesets import TileSetConverter
from project_settings import ProjectSettingsConverter
import threading
import webbrowser
import os

class ConverterGUI:
    def __init__(self, master):
        self.master = master
        master.title("GM2Godot")

        # GameMaker project path
        self.gm_label = tk.Label(master, text="GameMaker Project Path:")
        self.gm_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.gm_entry = tk.Entry(master, width=50)
        self.gm_entry.grid(row=0, column=1, padx=5, pady=5)
        self.gm_button = tk.Button(master, text="Browse GameMaker Path", command=self.browse_gm)
        self.gm_button.grid(row=0, column=2, padx=5, pady=5)

        # Godot project path
        self.godot_label = tk.Label(master, text="Godot Project Path:")
        self.godot_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.godot_entry = tk.Entry(master, width=50)
        self.godot_entry.grid(row=1, column=1, padx=5, pady=5)
        self.godot_button = tk.Button(master, text="Browse Godot Path", command=self.browse_godot)
        self.godot_button.grid(row=1, column=2, padx=5, pady=5)

        # Frame for buttons
        self.button_frame = tk.Frame(master)
        self.button_frame.grid(row=2, column=0, columnspan=3, pady=10)

        # Convert button
        self.convert_button = tk.Button(self.button_frame, text="Convert", command=self.start_conversion, width=10)
        self.convert_button.grid(row=0, column=0, padx=5)

        # Stop button
        self.stop_button = tk.Button(self.button_frame, text="Stop", command=self.stop_conversion, state=tk.DISABLED, width=10)
        self.stop_button.grid(row=0, column=1, padx=5)

        # Settings button
        self.settings_button = tk.Button(self.button_frame, text="Settings", command=self.open_settings, width=10)
        self.settings_button.grid(row=0, column=2, padx=5)

        # Console output
        self.console = scrolledtext.ScrolledText(master, height=15)
        self.console.grid(row=3, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")

        # Progress bar and percentage
        self.progress_frame = tk.Frame(master)
        self.progress_frame.grid(row=4, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        self.progress = ttk.Progressbar(self.progress_frame, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.progress_label = tk.Label(self.progress_frame, text="0%")
        self.progress_label.pack(side=tk.RIGHT, padx=5)

        # Version and creator info
        self.info_frame = tk.Frame(master)
        self.info_frame.grid(row=5, column=0, columnspan=3, pady=10)

        self.version_label = tk.Label(self.info_frame, text="Version 0.0.8", font=("Arial", 8))
        self.version_label.pack(side=tk.LEFT, padx=10)

        self.infiland_label = tk.Label(self.info_frame, text="Made by Infiland", font=("Arial", 8), cursor="hand2")
        self.infiland_label.pack(side=tk.RIGHT, padx=10)
        self.infiland_label.bind("<Button-1>", self.open_infiland_website)

        # Contribute hyperlink
        self.contribute_link = tk.Label(master, text="Contribute", fg="blue", cursor="hand2")
        self.contribute_link.grid(row=5, column=0, pady=5)
        self.contribute_link.bind("<Button-1>", self.open_github)

        # Configure grid
        master.grid_columnconfigure(1, weight=1)
        master.grid_rowconfigure(3, weight=1)

        # Initialize conversion settings
        self.conversion_running = threading.Event()
        self.conversion_settings = {
            "sprites": tk.BooleanVar(value=True),
            "sounds": tk.BooleanVar(value=True),
            "fonts": tk.BooleanVar(value=True),
            "tilesets": tk.BooleanVar(value=True),
            "objects": tk.BooleanVar(value=True),
            "notes": tk.BooleanVar(value=True),
            "shaders": tk.BooleanVar(value=True),
            "game_icon": tk.BooleanVar(value=True),
            "project_settings": tk.BooleanVar(value=True),
            "project_name": tk.BooleanVar(value=True),
            "audio_buses": tk.BooleanVar(value=True)
        }

        # Threading
        self.conversion_thread = None

    def open_settings(self):
        settings_window = tk.Toplevel(self.master)
        settings_window.title("Conversion Settings")
        settings_window.geometry("280x400")

        tk.Label(settings_window, text="Select files to convert:").pack(pady=10)

        for setting, var in self.conversion_settings.items():
            tk.Checkbutton(settings_window, text=setting.replace("_", " ").title(), variable=var).pack(anchor="w", padx=20)

        tk.Button(settings_window, text="Save", command=settings_window.destroy).pack(pady=20)

    def browse_gm(self):
        folder = filedialog.askdirectory()
        if folder:
            self.gm_entry.delete(0, tk.END)
            self.gm_entry.insert(0, folder)
            self.check_gm_project(folder)

    def browse_godot(self):
        folder = filedialog.askdirectory()
        if folder:
            self.godot_entry.delete(0, tk.END)
            self.godot_entry.insert(0, folder)
            self.check_godot_project(folder)

    def check_gm_project(self, folder):
        yyp_files = [f for f in os.listdir(folder) if f.endswith('.yyp')]
        if not yyp_files:
            messagebox.showwarning("Invalid GameMaker Project", "No .yyp file found in the selected GameMaker project folder.")
        elif len(yyp_files) > 1:
            messagebox.showwarning("Multiple .yyp Files", f"Multiple .yyp files found: {', '.join(yyp_files)}. Please ensure only one .yyp file is present.")
        else:
            self.log(f"GameMaker project file found: {yyp_files[0]}")

    def check_godot_project(self, folder):
        if not os.path.exists(os.path.join(folder, 'project.godot')):
            messagebox.showwarning("Invalid Godot Project", "No project.godot file found in the selected Godot project folder.")
        else:
            self.log("Godot project file found: project.godot")

    def log(self, message):
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)

    def update_progress(self, value):
        self.progress['value'] = value
        self.progress_label.config(text=f"{value}%")

    def start_conversion(self):
        gm_path = self.gm_entry.get()
        godot_path = self.godot_entry.get()

        if not gm_path or not godot_path:
            self.log("Please select both GameMaker and Godot project paths.")
            return

        # Check for project files
        yyp_files = [f for f in os.listdir(gm_path) if f.endswith('.yyp')]
        godot_project_file = os.path.join(godot_path, 'project.godot')

        if not yyp_files:
            self.log("Error: No .yyp file found in the GameMaker project folder.")
            return
        if len(yyp_files) > 1:
            self.log(f"Warning: Multiple .yyp files found: {', '.join(yyp_files)}. Using the first one.")
        if not os.path.exists(godot_project_file):
            self.log("Error: No project.godot file found in the Godot project folder.")
            return

        self.convert_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.conversion_running.set()  # This sets the event
        self.console.delete('1.0', tk.END)
        self.progress['value'] = 0
        self.progress_label.config(text="0%")
        self.log(f"Starting conversion...")
        self.log(f"GameMaker project file: {yyp_files[0]}")
        self.log(f"Godot project file: project.godot")

        # Start conversion in a separate thread
        self.conversion_thread = threading.Thread(target=self.convert, args=(gm_path, godot_path))
        self.conversion_thread.start()

    def stop_conversion(self):
        if self.conversion_running.is_set():
            self.conversion_running.clear()
            self.log("Stopping conversion process...")
            self.stop_button.config(state=tk.DISABLED)
            self.master.after(100, self.check_conversion_stopped)

    # MAIN CONVERSION IS HERE!!!
    def convert(self, gm_path, godot_path):
        project_settings_converter = ProjectSettingsConverter(gm_path, godot_path, self.threadsafe_log)

        # Handle project settings individually
        if self.conversion_settings["game_icon"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Converting game icon...")
            project_settings_converter.convert_icon()

        if self.conversion_settings["project_name"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Updating project name...")
            project_settings_converter.update_project_name()

        if self.conversion_settings["project_settings"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Updating project settings...")
            project_settings_converter.update_project_settings()

        if self.conversion_settings["audio_buses"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Generating audio bus layout...")
            project_settings_converter.generate_audio_bus_layout()

        # Convert sprites
        if self.conversion_settings["sprites"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Converting sprites...")
            sprite_converter = SpriteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set)
            sprite_converter.convert_all()

        # Convert fonts
        if self.conversion_settings["fonts"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Converting fonts...")
            font_converter = FontConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set)
            font_converter.convert_all()

        # Convert tilesets
        if self.conversion_settings["tilesets"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Converting tilesets...")
            tileset_converter = TileSetConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set)
            tileset_converter.convert_all()

        # Reset progress for sound conversion
        self.threadsafe_update_progress(0)

        # Convert sounds
        if self.conversion_settings["sounds"].get() and self.conversion_running.is_set():
            self.threadsafe_log("Converting sounds...")
            sound_converter = SoundConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set)
            sound_converter.convert_sounds()

        self.master.after(0, self.conversion_complete)

    def check_conversion_stopped(self):
        if self.conversion_thread and self.conversion_thread.is_alive():
            self.master.after(100, self.check_conversion_stopped)
        else:
            self.conversion_complete()

    def threadsafe_log(self, message):
        self.master.after(0, self.log, message)

    def threadsafe_update_progress(self, value):
        self.master.after(0, self.update_progress, value)

    def conversion_complete(self):
        self.progress['value'] = 100
        self.progress_label.config(text="100%")
        if self.conversion_running.is_set():
            self.log("You have ported your project from GameMaker to Godot! Have fun!")
        else:
            self.log("Conversion process stopped.")
        self.conversion_running.clear()
        self.convert_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def open_github(self, event):
        webbrowser.open_new("https://github.com/Infiland/GM2Godot")

    def open_infiland_website(self, event):
        webbrowser.open_new("https://infiland.github.io")

def main():
    root = tk.Tk()
    gui = ConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()