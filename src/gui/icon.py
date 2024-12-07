import platform
import os
import tkinter as tk
from tkinter import ttk

class Icon:
    def __init__(self, master):
        self.master = master
        self.base_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.set_program_icon()
        self.gm_icon = self.load_icon("img/Gamemaker.png")
        self.godot_icon = self.load_icon("img/Godot.png")
    
    def set_program_icon(self):
        icon_path = os.path.join(self.base_path, "img", "Logo.png")
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
            full_path = os.path.join(self.base_path, path)
            img = Image.open(full_path)
            return ImageTk.PhotoImage(img.resize((20, 20), Image.Resampling.LANCZOS))
        except Exception as e:
            print(f"Failed to load icon from {full_path}: {e}")
            return None
        
    def get_gamemaker_icon(self):
        return self.gm_icon
    
    def get_godot_icon(self):
        return self.godot_icon