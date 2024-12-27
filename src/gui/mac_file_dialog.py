import os
import tkinter as tk
from tkinter import filedialog

class MacFileDialog:
    @staticmethod
    def get_file_path(title, file_pattern=None):
        from tkinter import Tk
        import tkinter.filedialog as filedialog
        
        root = Tk()
        root.withdraw()
        
        if file_pattern:
            file_path = filedialog.askopenfilename(
                parent=root,
                title=title,
                initialdir=os.path.expanduser("~")
            )
        else:
            file_path = filedialog.askdirectory(
                parent=root,
                title=title,
                initialdir=os.path.expanduser("~")
            )
        
        root.destroy()
        return file_path

    def browse_project(self, entry, file_check, dialog_title, file_type=None):
        file = self.get_file_path(dialog_title, file_type)
        if file:
            directory = os.path.dirname(file) if file_type else file
            entry.delete(0, tk.END)
            entry.insert(0, directory)
            file_check(directory)

    def browse_gm(self):
        self.browse_project(self.setup_ui.entries['gamemaker'], self.check_gm_project, "Select your GameMaker Project File", "yyp")

    def browse_godot(self):
        self.browse_project(self.setup_ui.entries['godot'], self.check_godot_project, "Select your Godot Project File", "godot") 