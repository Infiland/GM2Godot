import tkinter as tk
from tkinter import messagebox, ttk
import requests
import markdown2
import webbrowser

from src.gui.theme import THEME
from src.localization import get_localized


class ReleaseNotesDialog:
    def __init__(self, master):
        self.master = master

    def show(self, event=None):
        notes = self._fetch()
        if notes:
            self._display(notes)
        else:
            messagebox.showerror(
                get_localized("ReleaseNotes_Error_NoInternet")[0],
                get_localized("ReleaseNotes_Error_NoInternet")[1]
            )

    def _fetch(self):
        try:
            response = requests.get(
                "https://api.github.com/repos/Infiland/GM2Godot/releases/latest"
            )
            if response.status_code == 200:
                return response.json()['body']
            return None
        except Exception as e:
            print(get_localized("ReleaseNotes_Error_Generic").format(error=e))
            return None

    def _display(self, notes):
        notes_window = tk.Toplevel(self.master)
        notes_window.title(get_localized("ReleaseNotes_Title"))
        notes_window.geometry("750x600")
        notes_window.configure(bg=THEME["bg_dialog"])

        html_content = markdown2.markdown(notes)

        text_widget = tk.Text(notes_window, wrap=tk.WORD, bg=THEME["bg_tertiary"], fg=THEME["fg_white"], font=(THEME["font_family"], THEME["font_size"]), padx=10, pady=10)
        text_widget.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

        scrollbar = ttk.Scrollbar(text_widget, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.tag_configure("h1", font=(THEME["font_family"], THEME["font_size_heading"], "bold"), spacing3=5)
        text_widget.tag_configure("h2", font=(THEME["font_family"], THEME["font_size_title"], "bold"), spacing3=5)
        text_widget.tag_configure("bullet", lmargin1=20, lmargin2=30)
        text_widget.tag_configure("link", foreground=THEME["accent_link"], underline=True)

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
                elif line.startswith('<a href='):  # This doesn't work :(
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
