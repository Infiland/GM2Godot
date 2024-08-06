import tkinter as tk

class ModernProgressBar(tk.Canvas):
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