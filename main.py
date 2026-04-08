import os
import threading
import time
import webbrowser
from functools import partial
import platform
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont
from src.gui.about import AboutDialog
from src.gui.release_notes import ReleaseNotesDialog
from src.gui.theme import THEME
from src.conversion.converter import Converter

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
        self.master.configure(bg=THEME["bg_primary"])
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

        self.release_notes = ReleaseNotesDialog(self.master)

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
        menubar = tk.Menu(self.master, bg=THEME["bg_primary"], fg=THEME["fg_primary"], activebackground=THEME["bg_secondary"], activeforeground=THEME["fg_white"])
        self.master.config(menu=menubar)

        help_menu = tk.Menu(menubar, tearoff=0, bg=THEME["bg_primary"], fg=THEME["fg_primary"], activebackground=THEME["bg_secondary"], activeforeground=THEME["fg_white"])
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
                "background": THEME["bg_primary"]
            },
            "TLabel": {
                "background": THEME["bg_primary"],
                "foreground": THEME["fg_primary"],
                "font": (THEME["font_family"], THEME["font_size"])
            },
            "TEntry": {
                "fieldbackground": THEME["bg_secondary"],
                "foreground": THEME["fg_primary"],
                "insertcolor": THEME["fg_primary"],
                "font": (THEME["font_family"], THEME["font_size"]),
                "borderwidth": 0,
                "relief": "flat"
            },
            "Modern.TButton": {
                "background": THEME["accent_blue"],
                "foreground": THEME["fg_white"],
                "font": (THEME["font_family"], THEME["font_size"], 'bold'),
                "padding": (15, 8),
                "borderwidth": 0,
                "relief": "flat"
            },
            "Icon.TButton": {
                "background": THEME["accent_red"],
                "foreground": THEME["fg_white"],
                "padding": 4,
                "borderwidth": 0,
                "relief": "flat",
                "width": 3,
                "anchor": "center"
            },
            "TCheckbutton": {
                "background": THEME["bg_primary"],
                "foreground": THEME["fg_primary"]
            },
            "Console.Vertical.TScrollbar": {
                "background": THEME["bg_secondary"],
                "troughcolor": THEME["bg_primary"],
                "arrowcolor": THEME["fg_primary"],
                "borderwidth": 0,
                "relief": "flat"
            },
            "Red.TButton": {
                "background": THEME["accent_red"],
                "foreground": THEME["fg_white"],
                "borderwidth": 0,
                "relief": "flat"
            },
            "TCombobox": {
                "background": THEME["bg_secondary"],
                "foreground": THEME["fg_primary"],
                "fieldbackground": THEME["bg_secondary"],
                "arrowcolor": THEME["fg_primary"],
                "font": (THEME["font_family"], THEME["font_size"]),
                "relief": "flat",
                "borderwidth": 0
            }
        }
        
        for style, options in styles.items():
            self.style.configure(style, **options)

        # Enhanced button states
        self.style.map("Modern.TButton",
            background=[('active', THEME["accent_blue_hover"]), ('disabled', THEME["disabled_bg"])],
            foreground=[('disabled', THEME["fg_disabled"])]
        )

        # Icon button states
        self.style.map("Icon.TButton",
            background=[('active', THEME["accent_red_hover"]), ('disabled', THEME["disabled_bg"])],
            foreground=[('disabled', THEME["fg_disabled"])]
        )

        self.style.map("TEntry",
            fieldbackground=[('readonly', THEME["bg_secondary"])],
            relief=[('focus', 'flat')]
        )

        self.style.map("TCheckbutton",
            background=[('active', THEME["bg_primary"])]
        )

        self.style.map("Red.TButton",
            background=[('active', THEME["accent_red_hover"])],
            foreground=[('disabled', THEME["fg_disabled"])]
        )

        # Enhanced Combobox states
        self.style.map("TCombobox",
            fieldbackground=[('readonly', THEME["bg_secondary"]), ('disabled', THEME["bg_primary"])],
            selectbackground=[('readonly', THEME["accent_blue"])],
            selectforeground=[('readonly', THEME["fg_white"])],
            background=[('readonly', THEME["bg_secondary"]), ('disabled', THEME["bg_primary"])],
            foreground=[('readonly', THEME["fg_primary"]), ('disabled', THEME["fg_disabled"])],
            arrowcolor=[('disabled', THEME["fg_disabled"])]
        )

        # Configure master window
        self.master.configure(bg=THEME["bg_primary"])
        self.master.option_add('*TCombobox*Listbox.background', THEME["bg_secondary"])
        self.master.option_add('*TCombobox*Listbox.foreground', THEME["fg_primary"])
        self.master.option_add('*TCombobox*Listbox.selectBackground', THEME["accent_blue"])
        self.master.option_add('*TCombobox*Listbox.selectForeground', THEME["fg_white"])
        self.master.option_add('*TCombobox*Listbox.font', (THEME["font_family"], THEME["font_size"]))
        self.master.option_add('*TCombobox*Listbox.relief', 'flat')
        self.master.option_add('*TCombobox*Listbox.borderwidth', '0')

    def setup_conversion_settings(self):
        from src.conversion.converter import CONVERSION_CATEGORIES
        all_keys = [key for keys in CONVERSION_CATEGORIES.values() for key in keys]
        self.conversion_settings = {key: tk.BooleanVar(value=True) for key in all_keys}
        self.conversion_settings["notes"].set(False)
        self.conversion_settings["objects"].set(False)
        self.compact_logging = tk.BooleanVar(value=True)

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
        settings_window.configure(bg=THEME["bg_primary"])
        settings_window.transient(self.master)  # Make it float on top of main window
        settings_window.grab_set()  # Make it modal

        main_frame = ttk.Frame(settings_window, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text=get_localized("Settings_Files_Heading"), style="TLabel", font=(THEME["font_family"], THEME["font_size_title"], "bold")).pack(pady=(0, 20))

        # Create a frame for the categories
        categories_frame = ttk.Frame(main_frame, style="TFrame")
        categories_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid weights for equal spacing
        categories_frame.grid_columnconfigure(0, weight=1)
        categories_frame.grid_columnconfigure(1, weight=1)
        categories_frame.grid_columnconfigure(2, weight=1)

        labels = get_localized("Settings_Labels")
        headings = get_localized("Settings_Categories_Headings")

        from src.conversion.converter import CONVERSION_CATEGORIES
        categories_items = list(CONVERSION_CATEGORIES.items())

        for idx, (cat_key, setting_keys) in enumerate(categories_items):
            category_frame = ttk.Frame(categories_frame, style="TFrame", padding="10 0")
            category_frame.grid(row=0, column=idx, sticky="n", padx=10)

            ttk.Label(category_frame, text=headings[idx],
                      style="TLabel", font=(THEME["font_family"], THEME["font_size_large"], "bold")).pack(pady=(0, 10))

            for key in setting_keys:
                display_name = labels.get(key, key.replace("_", " ").title())
                var = self.conversion_settings[key]
                ModernCheckbox(category_frame, text=display_name, variable=var).pack(pady=5, anchor="w")

        # Platform selection section
        platform_frame = ttk.Frame(main_frame, style="TFrame", padding="0 20")
        platform_frame.pack(fill=tk.X)
        
        platform_label_frame = ttk.Frame(platform_frame, style="TFrame")
        platform_label_frame.pack(fill=tk.X)
        
        ttk.Label(platform_label_frame, text=get_localized("Settings_Platform_Heading"), style="TLabel", font=(THEME["font_family"], THEME["font_size_title"], "bold")).pack(side=tk.LEFT)
        ttk.Label(platform_label_frame, text=get_localized("Settings_Platform_Subheading"),
                 style="TLabel", font=(THEME["font_family"], THEME["font_size"])).pack(side=tk.LEFT, padx=(10, 0))
        
        combobox_frame = ttk.Frame(platform_frame, style="TFrame")
        combobox_frame.pack(fill=tk.X, pady=(10, 0))
        
        platform_categories = ("linux", "macos", "windows")
        
        self.platform_combobox = ModernCombobox(combobox_frame, 
                                               values=platform_categories,
                                               state="readonly")
        self.platform_combobox.pack(fill=tk.X)
        self.platform_combobox.bind('<<ComboboxSelected>>', self.update_platform_settings)
        self.platform_combobox.set(self.gm_platform_settings)

        # Logging section
        logging_frame = ttk.Frame(main_frame, style="TFrame", padding="0 20")
        logging_frame.pack(fill=tk.X)

        ttk.Label(logging_frame, text=get_localized("Settings_Logging_Heading"),
                  style="TLabel", font=(THEME["font_family"], THEME["font_size_title"], "bold")).pack(anchor="w")

        ModernCheckbox(logging_frame, text=get_localized("Settings_Logging_Compact"),
                       variable=self.compact_logging).pack(pady=5, anchor="w")

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

    def update_log(self, message):
        """Replace the last content line in the console with message."""
        if self.console:
            self.console.configure(state='normal')
            # "end-1c" is at the implicit trailing newline in tk.Text.
            # After log(), content ends with an explicit \n, so the last
            # content line is one line above the empty trailing line.
            end_pos = self.console.index("end-1c")
            target_line = max(1, int(end_pos.split('.')[0]) - 1)
            self.console.delete(f"{target_line}.0", f"{target_line}.0 lineend")
            self.console.insert(f"{target_line}.0", message)
            self.console.see(tk.END)
            self.console.configure(state='disabled')

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

        compact_logging = self.compact_logging.get()
        self.prepare_for_conversion()
        self.conversion_thread = threading.Thread(target=self.convert, args=(gm_path, gm_platform, godot_path, compact_logging))
        self.conversion_thread.start()
        self.start_timer()
        self.style.configure("Red.TButton", background=THEME["accent_red"], foreground=THEME["fg_white"])
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
            self.style.configure("Red.TButton", background=THEME["fg_white"], foreground=THEME["fg_white"])
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

    def convert(self, gm_path, gm_platform, godot_path, compact_logging):
        converter = Converter(
            self.threadsafe_log,
            self.threadsafe_update_progress,
            self.threadsafe_update_status,
            self.conversion_running,
            update_log_callback=self.threadsafe_update_log,
            compact_logging=compact_logging,
        )
        converter.convert(gm_path, gm_platform, godot_path, self.conversion_settings)
        self.master.after(0, self.conversion_complete)

    def check_conversion_stopped(self):
        if self.conversion_thread and self.conversion_thread.is_alive():
            self.master.after(100, self.check_conversion_stopped)
        else:
            self.conversion_complete()

    def threadsafe_log(self, message):
        self.master.after(0, self.log, message)

    def threadsafe_update_log(self, message):
        self.master.after(0, self.update_log, message)

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
