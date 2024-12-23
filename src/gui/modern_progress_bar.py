import tkinter as tk
import colorsys

class ModernProgressBar(tk.Canvas):
    def __init__(self, master, width, height, bg_color, fill_color, text_color):
        super().__init__(master, width=width, height=height, bg=bg_color, highlightthickness=0)
        self.fill_color = fill_color
        self.text_color = text_color
        self.width = width
        self.height = height
        self.progress = 0
        
        # Create rounded rectangle background
        radius = height // 2
        self.create_rounded_rect(0, 0, width, height, radius, bg_color)
        
        # Create progress bar with gradient
        self.rect_id = self.create_rounded_rect(0, 0, 0, height, radius, fill_color)
        
        # Create text
        self.text_id = self.create_text(width // 2, height // 2,
                                      text="0%",
                                      fill=text_color,
                                      font=("Segoe UI", 12, "bold"))
        
        # Bind resize event
        self.bind('<Configure>', self.on_resize)

    def create_rounded_rect(self, x1, y1, x2, y2, radius, fill):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1
        ]
        return self.create_polygon(points, fill=fill, smooth=True)

    def get_progress_color(self, progress):
        # Start with red (0, 1, 0.5) and transition to green (120, 1, 0.5) in HSV
        hue = progress * 120 / 360  # Convert to 0-1 range for colorsys
        rgb = colorsys.hsv_to_rgb(hue, 0.8, 0.9)  # Using slightly desaturated, bright colors
        return f'#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}'

    def on_resize(self, event):
        # Update canvas size
        self.width = event.width
        self.height = event.height
        
        # Recreate background
        self.delete("all")
        radius = self.height // 2
        self.create_rounded_rect(0, 0, self.width, self.height, radius, self.cget('bg'))
        
        # Recreate progress bar
        fill_width = int(self.width * (self.progress / 100))
        self.rect_id = self.create_rounded_rect(0, 0, fill_width, self.height, radius, self.get_progress_color(self.progress/100))
        
        # Recreate text
        self.text_id = self.create_text(self.width // 2, self.height // 2,
                                      text=f"{self.progress}%",
                                      fill=self.text_color,
                                      font=("Segoe UI", 12, "bold"))

    def update_progress(self, value):
        self.progress = value
        fill_width = int(self.width * (value / 100))
        radius = self.height // 2
        
        # Update progress bar shape and color
        points = [
            radius, 0,
            fill_width - radius, 0,
            fill_width, 0,
            fill_width, radius,
            fill_width, self.height - radius,
            fill_width, self.height,
            fill_width - radius, self.height,
            radius, self.height,
            0, self.height,
            0, self.height - radius,
            0, radius,
            0, 0
        ]
        
        self.coords(self.rect_id, *points)
        self.itemconfig(self.rect_id, fill=self.get_progress_color(value/100))
        self.itemconfig(self.text_id, text=f"{value}%")
        self.lift(self.text_id)
        self.update_idletasks()