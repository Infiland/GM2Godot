import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

class ModernButton(ttk.Button):
    def __init__(self, master=None, icon_only=False, **kw):
        if icon_only:
            # For icon-only buttons, adjust padding and remove text styling
            kw['style'] = "Icon.TButton"
            if 'width' not in kw:
                kw['width'] = 3  # Make it square
        else:
            kw['style'] = "Modern.TButton"
            
        super().__init__(master, **kw)
        self.bind('<Enter>', self.on_enter)
        self.bind('<Leave>', self.on_leave)
        
    def on_enter(self, e):
        self.state(['active'])
        
    def on_leave(self, e):
        self.state(['!active'])

    @staticmethod
    def create_stop_icon(master, color="#ffffff", size=20):
        # Create a new image with RGBA
        image = Image.new('RGBA', (size, size), (216, 59, 1, 255))  # #d83b01 in RGBA
        draw = ImageDraw.Draw(image)
        
        # Draw a white square for the stop icon
        padding = size // 4
        draw.rectangle(
            [padding, padding, size - padding, size - padding],
            fill=color
        )
        
        # Convert to PhotoImage
        photo = ImageTk.PhotoImage(image)
        return photo