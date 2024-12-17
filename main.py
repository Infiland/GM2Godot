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

#TODO: REPLACE THIS WITH from src.conversion.converter import Converter
from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.project_settings import ProjectSettingsConverter

# Import Version
from src.version import get_version

# Import GUI
from src.gui.modern_button import ModernButton
from src.gui.icon import Icon
from src.gui.setupui import SetupUI

# Import localization manager
from src.localization import get_localized

class ConverterGUI:
    def __init__(self, master):
        self.language = "EN"
        
        self.master = master
        self.master.title(get_localized(self.language, 'Menu_Title').format(version=get_version()))
        self.master.geometry("800x600")
        self.master.configure(bg="#222222")
        self.icon = Icon(self.master)

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.setup_styles()

        self.setup_ui = SetupUI(self.master, self)
        self.setup_ui.setup_ui()

        self.console = self.setup_ui.console
        self.progress = self.setup_ui.progress
        self.timer_label = self.setup_ui.timer_label
        self.status_label = self.setup_ui.status_label

        self.convert_button = self.setup_ui.get_button(get_localized(self.language, 'Menu_UI_Button_Convert'))
        self.stop_button = self.setup_ui.get_button(get_localized(self.language, 'Menu_UI_Button_Stop'))

        self.setup_conversion_settings()
        self.conversion_running = threading.Event()
        self.conversion_thread = None
        self.timer_running = False
        self.start_time = 0
        
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

    def show_release_notes(self, event):
        release_notes = self.fetch_release_notes()
        if release_notes:
            self.display_release_notes(release_notes)
        else:
            messagebox.showerror(get_localized(self.language, 'ReleaseNotes_Error_NoInternet')[0], get_localized(self.language, 'ReleaseNotes_Error_NoInternet')[1])

    def fetch_release_notes(self):
        try:
            response = requests.get("https://api.github.com/repos/Infiland/GM2Godot/releases/latest")
            if response.status_code == 200:
                return response.json()['body']
            else:
                return None
        except Exception as e:
            print(get_localized(self.language, 'ReleaseNotes_Error_Generic').format(error=e))
            return None

    def display_release_notes(self, notes):
        notes_window = tk.Toplevel(self.master)
        notes_window.title(get_localized(self.language, 'ReleaseNotes_Title'))
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
        settings = get_localized(self.language, 'Settings_Files_Categories')
        
        self.conversion_settings = {setting: tk.BooleanVar(value=True) for setting in settings}
        self.conversion_settings["notes"].set(False)
        self.conversion_settings["objects"].set(False)

        match(platform.system()):  
            case "Linux":
                self.gm_platform_settings = "linux"
            case "Darwin":
                self.gm_platform_settings = "macos"
            case _:
                self.gm_platform_settings = "windows"

    def update_platform_settings(self, event):
        self.gm_platform_settings = self.platform_combobox.get()
        
    def open_settings(self):
        settings_window = tk.Toplevel(self.master)
        settings_window.title(get_localized(self.language, 'Settings_Title'))
        settings_window.geometry("460x640")
        settings_window.configure(bg="#222222")

        main_frame= ttk.Frame(settings_window, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True, anchor="w")
        
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

        ttk.Label(main_frame, text=get_localized(self.language, 'Settings_Platform_Heading'), style="TLabel", font=("Helvetica", 14, "bold")).pack(pady=10)
        ttk.Label(main_frame, text=get_localized(self.language, 'Settings_Platform_Subheading'), style="TLabel", font=("Helvetica", 10, "bold")).pack(pady=10)
        
        platform_categories = ("linux",
                               "macos",
                               "windows")
        
        combobox_frame = ttk.Frame(main_frame, style="TFrame")
        combobox_frame.pack(fill=tk.BOTH, expand=True)
        
        self.platform_combobox = ttk.Combobox(combobox_frame, values=platform_categories, textvariable=self.gm_platform_settings, state="readonly")
        self.platform_combobox.pack(pady=10)
        self.platform_combobox.bind('<<ComboboxSelected>>', self.update_platform_settings)
        self.platform_combobox.current(platform_categories.index(self.gm_platform_settings))

        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack()
        
        def select_all():
            for var in self.conversion_settings.values():
                var.set(True)

        def deselect_all():
            for var in self.conversion_settings.values():
                var.set(False)

        ModernButton(button_frame, text=get_localized(self.language, 'Settings_Button_SelectAll'), command=select_all).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text=get_localized(self.language, 'Settings_Button_DeselectAll'), command=deselect_all).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text=get_localized(self.language, 'Settings_Button_Save'), command=settings_window.destroy).pack(side=tk.RIGHT, padx=5)

    def log(self, message):
        if self.console:
            self.console.configure(state='normal')
            self.console.insert(tk.END, message + "\n")
            self.console.see(tk.END)
            self.console.configure(state='disabled')
        else:
            print(get_localized(self.language, 'Console_Error_NotInitialized').format(message=message))#f"Console not initialized. Message: {message}")

    def browse_project(self, entry, file_check, dialog_title):
        folder = filedialog.askdirectory(title=dialog_title)
        if folder:
            entry.delete(0, tk.END)
            entry.insert(0, folder)
            file_check(folder)

    def browse_gm(self):
        self.browse_project(self.setup_ui.entries['gamemaker'], self.check_gm_project, "Select your GameMaker Project")

    def browse_godot(self):
        self.browse_project(self.setup_ui.entries['godot'], self.check_godot_project, "Select your new Godot project")

    def check_project_file(self, folder, file_extension, file_name):
        files = [f for f in os.listdir(folder) if f.endswith(file_extension)]
        if not files:
            messagebox.showwarning(get_localized(self.language, 'Console_Error_InvalidProject')[0].format(file_name=file_name), get_localized(self.language, 'Console_Error_InvalidProject')[1].format(file_name=file_name, file_extension=file_extension))
        elif len(files) > 1:
            messagebox.showwarning(get_localized(self.language, 'Console_Error_MultipleGenericFiles')[0].format(file_extension=file_extension), get_localized(self.language, 'Console_Error_MultipleGenericFiles')[1].format(file_extension=file_extension, files=', '.join(files)))
        else:
            self.log(get_localized(self.language, 'Console_ProjectFound').format(file_name=file_name, files=files[0]))

    def check_gm_project(self, folder):
        self.check_project_file(folder, '.yyp', 'GameMaker')

    def check_godot_project(self, folder):
        self.check_project_file(folder, 'project.godot', 'Godot')

    def update_progress(self, value):
        self.progress['value'] = value
        self.progress_label.config(text=f"{value}%")

    def start_conversion(self):
        gm_path, gm_platform, godot_path = self.setup_ui.entries['gamemaker'].get(), self.gm_platform_settings, self.setup_ui.entries['godot'].get()
        if not gm_path or not godot_path:
            self.log(get_localized(self.language, 'Console_Error_MissingDirectories'))
            return

        if not self.validate_projects(gm_path, godot_path):
            return

        self.prepare_for_conversion()
        self.conversion_thread = threading.Thread(target=self.convert, args=(gm_path, gm_platform, godot_path))
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
            self.log(get_localized(self.language, 'Console_Error_MissingGamemakerFile'))
        elif len(yyp_files) > 1:
            self.log(get_localized(self.language, 'Console_Error_MultipleGamemakerFiles').format(yyp_files=', '.join(yyp_files)))
        if not os.path.exists(godot_project_file):
            self.log(get_localized(self.language, 'Console_Error_MissingGodotFile'))

    def prepare_for_conversion(self):
        self.convert_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.conversion_running.set()
        self.console.delete('1.0', tk.END)
        self.progress.update_progress(0)
        self.log(get_localized(self.language, 'Console_ConversionStart'))

    def stop_conversion(self):
        if self.conversion_running.is_set():
            self.conversion_running.clear()
            self.log(get_localized(self.language, 'Console_ConversionStopping'))
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

    def convert(self, gm_path, gm_platform_settings_path, godot_path):
        project_settings_converter = ProjectSettingsConverter(gm_path, gm_platform_settings_path, godot_path, self.threadsafe_log)

        converters = [
            ("game_icon", project_settings_converter.convert_icon, get_localized(self.language, 'Console_Convertor_Icon')),
            ("project_name", project_settings_converter.update_project_name, get_localized(self.language, 'Console_Convertor_Name')),
            ("project_settings", project_settings_converter.update_project_settings, get_localized(self.language, 'Console_Convertor_Settings')),
            ("audio_buses", project_settings_converter.generate_audio_bus_layout, get_localized(self.language, 'Console_Convertor_AudioBus')),
            ("sprites", lambda: SpriteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Sprites')),
            ("fonts", lambda: FontConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Fonts')),
            ("tilesets", lambda: TileSetConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Tilesets')),
            ("sounds", lambda: SoundConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_sounds(), get_localized(self.language, 'Console_Convertor_Sounds')),
            ("notes", lambda: NoteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized(self.language, 'Console_Convertor_Notes'))
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
        self.status_label.config(text=get_localized(self.language, 'Console_ConversionComplete'))
        self.log(get_localized(self.language, 'Console_ConversionComplete_B') if self.conversion_running.is_set() else get_localized(self.language, 'Console_ConversionStopped'))
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
