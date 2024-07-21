import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk
from sprites import SpriteConverter
import threading
import webbrowser

class ConverterGUI:
    def __init__(self, master):
        self.master = master
        master.title("GM2Godot")

        # GameMaker project path
        self.gm_label = tk.Label(master, text="GameMaker Project Path:")
        self.gm_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.gm_entry = tk.Entry(master, width=50)
        self.gm_entry.grid(row=0, column=1, padx=5, pady=5)
        self.gm_button = tk.Button(master, text="Browse", command=self.browse_gm)
        self.gm_button.grid(row=0, column=2, padx=5, pady=5)

        # Godot project path
        self.godot_label = tk.Label(master, text="Godot Project Path:")
        self.godot_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.godot_entry = tk.Entry(master, width=50)
        self.godot_entry.grid(row=1, column=1, padx=5, pady=5)
        self.godot_button = tk.Button(master, text="Browse", command=self.browse_godot)
        self.godot_button.grid(row=1, column=2, padx=5, pady=5)

        # Convert button
        self.convert_button = tk.Button(master, text="Convert", command=self.start_conversion)
        self.convert_button.grid(row=2, column=1, pady=10)

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

        # Contribute hyperlink
        self.contribute_link = tk.Label(master, text="Contribute", fg="blue", cursor="hand2")
        self.contribute_link.grid(row=5, column=0, pady=5)
        self.contribute_link.bind("<Button-1>", self.open_github)

        # Configure grid
        master.grid_columnconfigure(1, weight=1)
        master.grid_rowconfigure(3, weight=1)

    def browse_gm(self):
        folder = filedialog.askdirectory()
        self.gm_entry.delete(0, tk.END)
        self.gm_entry.insert(0, folder)

    def browse_godot(self):
        folder = filedialog.askdirectory()
        self.godot_entry.delete(0, tk.END)
        self.godot_entry.insert(0, folder)

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

        self.convert_button.config(state=tk.DISABLED)
        self.console.delete('1.0', tk.END)
        self.progress['value'] = 0
        self.progress_label.config(text="0%")
        self.log("Starting conversion...")

        # Start conversion in a separate thread
        thread = threading.Thread(target=self.convert, args=(gm_path, godot_path))
        thread.start()

    def convert(self, gm_path, godot_path):
        converter = SpriteConverter(gm_path, godot_path, self.threadsafe_log, self.threadsafe_update_progress)
        converter.convert_sprites()
        self.master.after(0, self.conversion_complete)

    def threadsafe_log(self, message):
        self.master.after(0, self.log, message)

    def threadsafe_update_progress(self, value):
        self.master.after(0, self.update_progress, value)

    def conversion_complete(self):
        self.progress['value'] = 100
        self.progress_label.config(text="100%")
        self.log("Conversion process finished.")
        self.convert_button.config(state=tk.NORMAL)

    def open_github(self, event):
        webbrowser.open_new("https://github.com/Infiland/GM2Godot")

def main():
    root = tk.Tk()
    gui = ConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()