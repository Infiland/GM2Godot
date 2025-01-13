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
from src.gui.about import AboutDialog
from src.conversion.sprites import SpriteConverter
from src.conversion.sounds import SoundConverter
from src.conversion.fonts import FontConverter
from src.conversion.notes import NoteConverter
from src.conversion.tilesets import TileSetConverter
from src.conversion.project_settings import ProjectSettingsConverter

from src.version import get_version

from src.gui.modern_widgets import ModernButton, ModernCheckbox, ModernCombobox
from src.gui.icon import Icon
from src.gui.setupui import SetupUI

# Import localization manager
from src.localization import get_localized

class ConverterGUI:
    def __init__(self, master):
        
        self.master = master
        self.master.title(get_localized("Menu_Title").format(version=get_version()))
        self.master.geometry("800x600")
        self.master.configure(bg="#1e1e1e")
        self.icon = Icon(self.master)
        
        # Add window padding
        self.master.grid_columnconfigure(0, weight=1, minsize=20)
        self.master.grid_columnconfigure(2, weight=1, minsize=20)
        self.master.grid_rowconfigure(0, weight=1, minsize=20)
        self.master.grid_rowconfigure(2, weight=1, minsize=20)

        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.setup_styles()

        self.create_menu()

        self.setup_ui = SetupUI(self.master, self)
        self.setup_ui.setup_ui()

        self.console = self.setup_ui.console
        self.progress = self.setup_ui.progress
        self.timer_label = self.setup_ui.timer_label
        self.status_label = self.setup_ui.status_label

        self.convert_button = self.setup_ui.get_button(get_localized("Menu_UI_Button_Convert"))
        self.stop_button = self.setup_ui.get_button(get_localized("Menu_UI_Button_Stop"))

        self.setup_conversion_settings()
        self.conversion_running = threading.Event()
        self.conversion_thread = None
        self.timer_running = False
        self.start_time = 0

    def create_menu(self):
        """Create the menu bar with Help menu."""
        menubar = tk.Menu(self.master, bg="#1e1e1e", fg="#e0e0e0", activebackground="#2d2d2d", activeforeground="#ffffff")
        self.master.config(menu=menubar)

        help_menu = tk.Menu(menubar, tearoff=0, bg="#1e1e1e", fg="#e0e0e0", activebackground="#2d2d2d", activeforeground="#ffffff")
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About GM2Godot", command=self.show_about)
        help_menu.add_separator()
        help_menu.add_command(label="Documentation", command=lambda: webbrowser.open("https://github.com/Infiland/GM2Godot/wiki"))
        help_menu.add_command(label="Report Issue", command=lambda: webbrowser.open("https://github.com/Infiland/GM2Godot/issues"))

    def show_about(self):
        """Show the About dialog."""
        AboutDialog(self.master)

    def setup_styles(self):
        styles = {
            "TFrame": {
                "background": "#1e1e1e"  # Darker background for better contrast
            },
            "TLabel": {
                "background": "#1e1e1e",
                "foreground": "#e0e0e0",  # Softer white for better readability
                "font": ('Segoe UI', 10)  # Modern system font
            },
            "TEntry": {
                "fieldbackground": "#2d2d2d",
                "foreground": "#e0e0e0",
                "insertcolor": "#e0e0e0",
                "font": ('Segoe UI', 10),
                "borderwidth": 0,
                "relief": "flat"
            },
            "Modern.TButton": {
                "background": "#0078d4",  # Modern blue
                "foreground": "#ffffff",
                "font": ('Segoe UI', 10, 'bold'),
                "padding": (15, 8),
                "borderwidth": 0,
                "relief": "flat"
            },
            "Icon.TButton": {
                "background": "#d83b01",  # Modern red for stop button
                "foreground": "#ffffff",
                "padding": 4,
                "borderwidth": 0,
                "relief": "flat",
                "width": 3,  # Make it square
                "anchor": "center"
            },
            "TCheckbutton": {
                "background": "#1e1e1e",
                "foreground": "#e0e0e0"
            },
            "Console.Vertical.TScrollbar": {
                "background": "#2d2d2d",
                "troughcolor": "#1e1e1e",
                "arrowcolor": "#e0e0e0",
                "borderwidth": 0,
                "relief": "flat"
            },
            "Red.TButton": {
                "background": "#d83b01",  # Modern red
                "foreground": "#ffffff",
                "borderwidth": 0,
                "relief": "flat"
            },
            "TCombobox": {
                "background": "#2d2d2d",
                "foreground": "#e0e0e0",
                "fieldbackground": "#2d2d2d",
                "arrowcolor": "#e0e0e0",
                "font": ('Segoe UI', 10),
                "relief": "flat",
                "borderwidth": 0
            }
        }
        
        for style, options in styles.items():
            self.style.configure(style, **options)

        # Enhanced button states
        self.style.map("Modern.TButton",
            background=[('active', '#106ebe'), ('disabled', '#333333')],
            foreground=[('disabled', '#666666')]
        )
        
        # Icon button states
        self.style.map("Icon.TButton",
            background=[('active', '#a62d00'), ('disabled', '#333333')],
            foreground=[('disabled', '#666666')]
        )
        
        self.style.map("TEntry",
            fieldbackground=[('readonly', '#2d2d2d')],
            relief=[('focus', 'flat')]
        )
        
        self.style.map("TCheckbutton",
            background=[('active', '#1e1e1e')]
        )
        
        self.style.map("Red.TButton",
            background=[('active', '#a62d00')],
            foreground=[('disabled', '#666666')]
        )
        
        # Enhanced Combobox states
        self.style.map("TCombobox",
            fieldbackground=[('readonly', '#2d2d2d'), ('disabled', '#1e1e1e')],
            selectbackground=[('readonly', '#0078d4')],
            selectforeground=[('readonly', '#ffffff')],
            background=[('readonly', '#2d2d2d'), ('disabled', '#1e1e1e')],
            foreground=[('readonly', '#e0e0e0'), ('disabled', '#666666')],
            arrowcolor=[('disabled', '#666666')]
        )

        # Configure master window
        self.master.configure(bg="#1e1e1e")
        self.master.option_add('*TCombobox*Listbox.background', '#2d2d2d')
        self.master.option_add('*TCombobox*Listbox.foreground', '#e0e0e0')
        self.master.option_add('*TCombobox*Listbox.selectBackground', '#0078d4')
        self.master.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
        self.master.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        self.master.option_add('*TCombobox*Listbox.relief', 'flat')
        self.master.option_add('*TCombobox*Listbox.borderwidth', '0')

    def show_release_notes(self, event):
        release_notes = self.fetch_release_notes()
        if release_notes:
            self.display_release_notes(release_notes)
        else:
             messagebox.showerror(get_localized("ReleaseNotes_Error_NoInternet")[0], get_localized("ReleaseNotes_Error_NoInternet")[1])

    def fetch_release_notes(self):
        try:
            response = requests.get("https://api.github.com/repos/Infiland/GM2Godot/releases/latest")
            if response.status_code == 200:
                return response.json()['body']
            else:
                return None
        except Exception as e:
            print(get_localized("ReleaseNotes_Error_Generic").format(error=e))
            return None

    def display_release_notes(self, notes):
        notes_window = tk.Toplevel(self.master)
        notes_window.title(get_localized("ReleaseNotes_Title"))
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
        #settings = (set(item for sublist in get_localized("Settings_Categories_Contents") for item in sublist)) # merges all setting categories into a single array
        class settings_contents:
            values = ["sprites", "fonts", "sounds", "game_icon", "project_name", "project_settings", "audio_buses", "notes", "objects", "shaders", "tilesets"]
            
            sprites = get_localized("Settings_Categories_Contents")[0][0]
            fonts = get_localized("Settings_Categories_Contents")[0][1]
            sounds = get_localized("Settings_Categories_Contents")[0][2]
            
            game_icon = get_localized("Settings_Categories_Contents")[1][0]
            project_name = get_localized("Settings_Categories_Contents")[1][1]
            project_settings = get_localized("Settings_Categories_Contents")[1][2]
            audio_buses = get_localized("Settings_Categories_Contents")[1][3]
            notes = get_localized("Settings_Categories_Contents")[1][4]

            objects = get_localized("Settings_Categories_Contents")[2][0]
            shaders = get_localized("Settings_Categories_Contents")[2][1]
            tilesets = get_localized("Settings_Categories_Contents")[2][2]

        settings = settings_contents()
        
        self.conversion_settings = {settings.values[i] : tk.BooleanVar(value=True) for i in range(len(settings.values))}
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
        settings_window.title(get_localized("Settings_Title"))
        settings_window.geometry("800x500")  # Wider window for horizontal layout
        settings_window.configure(bg="#1e1e1e")
        settings_window.transient(self.master)  # Make it float on top of main window
        settings_window.grab_set()  # Make it modal

        main_frame = ttk.Frame(settings_window, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text=get_localized("Settings_Files_Heading"), style="TLabel", font=("Segoe UI", 14, "bold")).pack(pady=(0, 20))

        # Create a frame for the categories
        categories_frame = ttk.Frame(main_frame, style="TFrame")
        categories_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid weights for equal spacing
        categories_frame.grid_columnconfigure(0, weight=1)
        categories_frame.grid_columnconfigure(1, weight=1)
        categories_frame.grid_columnconfigure(2, weight=1)

        categories = {
            get_localized("Settings_Categories_Headings")[0] : get_localized("Settings_Categories_Contents")[0],
            get_localized("Settings_Categories_Headings")[1] : get_localized("Settings_Categories_Contents")[1],
            get_localized("Settings_Categories_Headings")[2] : get_localized("Settings_Categories_Contents")[2]
        }

        # Create frames for each category
        for idx, (category, settings) in enumerate(categories.items()):
            category_frame = ttk.Frame(categories_frame, style="TFrame", padding="10 0")
            category_frame.grid(row=0, column=idx, sticky="n", padx=10)
            
            ttk.Label(category_frame, text=category, style="TLabel", font=("Segoe UI", 12, "bold")).pack(pady=(0, 10))
            
            for setting in settings:
                var = self.conversion_settings[setting]
                ModernCheckbox(category_frame, text=setting.replace("_", " ").title(), variable=var).pack(pady=5, anchor="w")

        # Platform selection section
        platform_frame = ttk.Frame(main_frame, style="TFrame", padding="0 20")
        platform_frame.pack(fill=tk.X)
        
        platform_label_frame = ttk.Frame(platform_frame, style="TFrame")
        platform_label_frame.pack(fill=tk.X)
        
        ttk.Label(platform_label_frame, text=get_localized("Settings_Platform_Heading"), style="TLabel", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        ttk.Label(platform_label_frame, text=get_localized("Settings_Platform_Subheading"), 
                 style="TLabel", font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(10, 0))
        
        combobox_frame = ttk.Frame(platform_frame, style="TFrame")
        combobox_frame.pack(fill=tk.X, pady=(10, 0))
        
        platform_categories = ("linux", "macos", "windows")
        
        self.platform_combobox = ModernCombobox(combobox_frame, 
                                               values=platform_categories,
                                               state="readonly")
        self.platform_combobox.pack(fill=tk.X)
        self.platform_combobox.bind('<<ComboboxSelected>>', self.update_platform_settings)
        self.platform_combobox.set(self.gm_platform_settings)

        # Buttons frame
        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=(20, 0))
        
        def select_all():
            for var in self.conversion_settings.values():
                var.set(True)

        def deselect_all():
            for var in self.conversion_settings.values():
                var.set(False)

        ModernButton(button_frame, text=get_localized("Settings_Button_SelectAll"), command=select_all).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text=get_localized("Settings_Button_DeselectAll"), command=deselect_all).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text=get_localized("Settings_Button_Save"), command=settings_window.destroy).pack(side=tk.RIGHT, padx=5)

    def log(self, message):
        if self.console:
            self.console.configure(state='normal')
            self.console.insert(tk.END, message + "\n")
            self.console.see(tk.END)
            self.console.configure(state='disabled')
        else:
            print(get_localized("Console_Error_NotInitialized").format(message=message))

    def browse_project(self, entry, file_check, dialog_title):
        folder = filedialog.askdirectory(title=dialog_title)
        if folder:
            entry.delete(0, tk.END)
            entry.insert(0, folder)
            file_check(folder)

    def browse_gm(self):
        self.browse_project(self.setup_ui.entries["gamemaker"], self.check_gm_project, get_localized("Prompt_Path_GameMaker"))

    def browse_godot(self):
        self.browse_project(self.setup_ui.entries["godot"], self.check_godot_project, get_localized("Prompt_Path_Godot"))

    def check_project_file(self, folder, file_extension, file_name):
        files = [f for f in os.listdir(folder) if f.endswith(file_extension)]
        if not files:
            messagebox.showwarning(get_localized("Console_Error_InvalidProject")[0].format(file_name=file_name), get_localized("Console_Error_InvalidProject")[1].format(file_name=file_name, file_extension=file_extension))
        elif len(files) > 1:
            messagebox.showwarning(get_localized("Console_Error_MultipleGenericFiles")[0].format(file_extension=file_extension), get_localized("Console_Error_MultipleGenericFiles")[1].format(file_extension=file_extension, files=', '.join(files)))
        else:
            self.log(get_localized("Console_ProjectFound").format(file_name=file_name, files=files[0]))

    def check_gm_project(self, folder):
        self.check_project_file(folder, '.yyp', 'GameMaker')

    def check_godot_project(self, folder):
        self.check_project_file(folder, 'project.godot', 'Godot')

    def update_progress(self, value):
        self.progress['value'] = value
        self.progress_label.config(text=f"{value}%")

    def start_conversion(self):
        gm_path, gm_platform, godot_path = self.setup_ui.entries["gamemaker"].get(), self.gm_platform_settings, self.setup_ui.entries["godot"].get()
        if not gm_path or not godot_path:
            self.log(get_localized("Console_Error_MissingDirectories"))
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
            self.log(get_localized("Console_Error_MissingGamemakerFile"))
        elif len(yyp_files) > 1:
            self.log(get_localized("Console_Error_MultipleGamemakerFiles").format(yyp_files=', '.join(yyp_files)))
        if not os.path.exists(godot_project_file):
            self.log(get_localized("Console_Error_MissingGodotFile"))

    def prepare_for_conversion(self):
        self.convert_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.conversion_running.set()
        self.console.delete('1.0', tk.END)
        self.progress.update_progress(0)
        self.log(get_localized("Console_ConversionStart"))

    def stop_conversion(self):
        if self.conversion_running.is_set():
            self.conversion_running.clear()
            self.log(get_localized("Console_ConversionStopping"))
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
            time_str = f"{get_localized('Menu_UI_Time_Heading')} {hours:02d}:{minutes:02d}:{seconds:02d}"
            self.timer_label.config(text=time_str)
            self.master.after(1000, self.update_timer)

    def convert(self, gm_path, gm_platform_settings_path, godot_path):
        project_settings_converter = ProjectSettingsConverter(gm_path, gm_platform_settings_path, godot_path, self.threadsafe_log)

        converters = [
            (get_localized("Settings_Categories_Contents")[1][0], project_settings_converter.convert_icon, get_localized("Console_Convertor_Icon")),
            (get_localized("Settings_Categories_Contents")[1][1], project_settings_converter.update_project_name, get_localized("Console_Convertor_Name")),
            (get_localized("Settings_Categories_Contents")[1][2], project_settings_converter.update_project_settings, get_localized("Console_Convertor_Settings")),
            (get_localized("Settings_Categories_Contents")[1][3], project_settings_converter.generate_audio_bus_layout, get_localized("Console_Convertor_AudioBus")),
            (get_localized("Settings_Categories_Contents")[0][0], lambda: SpriteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized("Console_Convertor_Sprites")),
            (get_localized("Settings_Categories_Contents")[0][1], lambda: FontConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized("Console_Convertor_Fonts")),
            (get_localized("Settings_Categories_Contents")[2][2], lambda: TileSetConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized("Console_Convertor_Tilesets")),
            (get_localized("Settings_Categories_Contents")[0][2], lambda: SoundConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_sounds(), get_localized("Console_Convertor_Sounds")),
            (get_localized("Settings_Categories_Contents")[1][4], lambda: NoteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress, self.conversion_running.is_set).convert_all(), get_localized("Console_Convertor_Notes"))
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
        self.status_label.config(text=get_localized("Console_ConversionComplete"))
        self.log(get_localized("Console_ConversionComplete_B")) if self.conversion_running.is_set() else get_localized("Console_ConversionStopped")
        self.conversion_running.clear()
        self.convert_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.stop_timer()

    def open_github(self, event):
        webbrowser.open_new("https://github.com/Infiland/GM2Godot")

    def open_infiland_website(self, event):
        webbrowser.open_new("https://infi.land")

def main():
    root = tk.Tk()
    ConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
