import glob, os, json, sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont
from tkhtmlview import HTMLLabel

from src.gui.modern_widgets import ModernButton, ModernCheckbox, ModernCombobox
from src.gui.icon import Icon

from src.localization import get_localized


def get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class language_options_window :
    def __init__(self, master):
        self.master = master

    def apply_new_language(self):
        try :
            with open(f"{get_base_path()}/Languages/{self.available_languages_keys[self.combobox_language.current()]}.json", 'r') as file:
                new_language = json.load(file)["Language_Code"]
        except:
            new_language = "eng" # Fallback to English

        with open(f"{get_base_path()}/Current Language", 'w') as file:
            try :
                file.write(new_language)
            except :
                pass

        # Restart the application to apply changes
        os.execl(sys.executable, sys.executable, * sys.argv)
        sys.exit()

    def open_window(self, master):
        self.language_window = tk.Toplevel(self.master)
        self.language_window.title(get_localized("Language_Select_Title"))
        self.language_window.geometry("300x150")  # Wider window for horizontal layout
        self.language_window.configure(bg="#1e1e1e")
        self.language_window.transient(self.master)  # Make it float on top of main window

        main_frame = ttk.Frame(self.language_window, padding="20 20 20 20", style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)

        available_languages_directory = glob.glob(f"{get_base_path()}/Languages/*.json")
        self.available_languages_names = []
        self.available_languages_keys = []
        self.current_language = 0
        self.current_language_key = ""

        try :
            with open(f"{get_base_path()}/Current Language", 'r') as file:
                self.current_language_key = file.read()
        except :
            pass

        for i in range(len(available_languages_directory)):
                with open(available_languages_directory[i], 'r') as file:
                    try :
                        language_json_file = json.load(file)
                        self.available_languages_keys.append(language_json_file["Language_Code"])
                        self.available_languages_names.append(language_json_file["Language"])

                        if (language_json_file["Language_Code"] == self.current_language_key):
                            self.current_language = i
                    except:
                        pass

        combobox_frame = ttk.Frame(main_frame, style="TFrame")
        combobox_frame.pack(fill=tk.X, pady=(10, 0))

        self.combobox_language = ModernCombobox(combobox_frame,
                                                values=self.available_languages_names,
                                                state="readonly")
        self.combobox_language.pack(fill=tk.X)
        self.combobox_language.set(self.available_languages_names[self.current_language])

        # Buttons frame
        button_frame = ttk.Frame(main_frame, style="TFrame")
        button_frame.pack(pady=(20, 0))

        ModernButton(button_frame, text=get_localized("Language_Select_Button_Save"), command=self.apply_new_language).pack(side=tk.LEFT, padx=5)
        ModernButton(button_frame, text=get_localized("Language_Select_Button_Cancel"), command=self.language_window.destroy).pack(side=tk.RIGHT, padx=5)
