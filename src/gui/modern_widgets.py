import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

from src.gui.theme import THEME

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
    def create_stop_icon(master, color=None, size=20):
        if color is None:
            color = THEME["fg_white"]
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

class ModernCheckbox(ttk.Checkbutton):
    def __init__(self, master=None, **kw):
        # Create custom style for this instance
        style_name = f"Modern.TCheckbutton.{id(self)}"
        style = ttk.Style()
        
        # Configure the custom style
        style.configure(style_name,
                      background=THEME["bg_primary"],
                      foreground=THEME["fg_primary"],
                      font=(THEME["font_family"], THEME["font_size"]))
        
        # Create images for different states
        self.images = self._create_checkbox_images()
        
        # Configure style element
        style.element_create(f'Indicator.{style_name}', 'image', self.images['unchecked'],
            ('selected', '!disabled', self.images['checked']),
            ('selected', 'disabled', self.images['checked_disabled']),
            ('!selected', 'disabled', self.images['unchecked_disabled']),
            ('selected', '!disabled', 'active', self.images['checked_hover']),
            ('!selected', '!disabled', 'active', self.images['unchecked_hover']))
        
        # Layout the custom style
        style.layout(style_name, [
            ('Checkbutton.padding', {
                'sticky': 'nswe',
                'children': [
                    (f'Indicator.{style_name}', {'side': 'left', 'sticky': ''}),
                    ('Checkbutton.focus', {
                        'side': 'left',
                        'sticky': '',
                        'children': [
                            ('Checkbutton.label', {'sticky': 'nswe'})
                        ]
                    })
                ]
            })
        ])
        
        kw['style'] = style_name
        super().__init__(master, **kw)
        
        # Bind hover events
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        
    def _create_checkbox_images(self, size=20):
        images = {}
        
        # Colors
        colors = {
            'bg': THEME["bg_secondary"],
            'bg_hover': THEME["bg_tertiary"],
            'bg_disabled': THEME["bg_primary"],
            'check': THEME["accent_blue"],
            'check_hover': THEME["accent_blue_light"],
            'check_disabled': THEME["border"],
            'border': THEME["border"],
            'border_hover': THEME["border_hover"]
        }
        
        states = {
            'unchecked': (colors['bg'], colors['border'], None),
            'checked': (colors['bg'], colors['border'], colors['check']),
            'unchecked_hover': (colors['bg_hover'], colors['border_hover'], None),
            'checked_hover': (colors['bg_hover'], colors['border_hover'], colors['check_hover']),
            'unchecked_disabled': (colors['bg_disabled'], colors['border'], None),
            'checked_disabled': (colors['bg_disabled'], colors['border'], colors['check_disabled'])
        }
        
        for state, (bg, border, check) in states.items():
            image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            
            # Draw rounded rectangle background
            draw.rounded_rectangle([0, 0, size-1, size-1], radius=4, fill=bg, outline=border)
            
            # Draw checkmark if needed
            if check:
                # Draw modern checkmark
                check_points = [
                    (size * 0.2, size * 0.5),
                    (size * 0.45, size * 0.75),
                    (size * 0.8, size * 0.25)
                ]
                draw.line(check_points, fill=check, width=2, joint="curve")
            
            images[state] = ImageTk.PhotoImage(image)
        
        return images
        
    def _on_enter(self, event):
        self.state(['active'])
        
    def _on_leave(self, event):
        self.state(['!active'])

class ModernCombobox(ttk.Combobox):
    def __init__(self, master=None, **kw):
        # Create custom style for this instance
        style_name = f"Modern.TCombobox.{id(self)}"
        style = ttk.Style()
        
        # Configure the custom style
        style.configure(style_name,
                      background=THEME["bg_secondary"],
                      foreground=THEME["fg_primary"],
                      fieldbackground=THEME["bg_secondary"],
                      arrowcolor=THEME["fg_primary"],
                      borderwidth=0,
                      relief="flat",
                      padding=5)

        # Configure the dropdown list style
        style.map(style_name,
                 fieldbackground=[('readonly', THEME["bg_secondary"]), ('disabled', THEME["bg_primary"])],
                 selectbackground=[('readonly', THEME["accent_blue"])],
                 selectforeground=[('readonly', THEME["fg_white"])],
                 background=[('readonly', THEME["bg_secondary"]), ('disabled', THEME["bg_primary"])],
                 foreground=[('readonly', THEME["fg_primary"]), ('disabled', THEME["fg_disabled"])],
                 arrowcolor=[('disabled', THEME["fg_disabled"])])
        
        # Define the layout for the combobox
        style.layout(style_name, [
            ('Combobox.padding', {'children': [
                ('Combobox.background', {'children': [
                    ('Combobox.textfield', {'side': 'left', 'sticky': 'nswe'}),
                    ('Combobox.arrow', {'side': 'right', 'sticky': 'nswe'})
                ], 'sticky': 'nswe'})
            ], 'sticky': 'nswe'})
        ])
        
        kw['style'] = style_name
        if 'font' not in kw:
            kw['font'] = (THEME["font_family"], THEME["font_size"])

        super().__init__(master, **kw)

        # Configure dropdown list appearance
        self.option_add('*TCombobox*Listbox.background', THEME["bg_secondary"])
        self.option_add('*TCombobox*Listbox.foreground', THEME["fg_primary"])
        self.option_add('*TCombobox*Listbox.selectBackground', THEME["accent_blue"])
        self.option_add('*TCombobox*Listbox.selectForeground', THEME["fg_white"])
        self.option_add('*TCombobox*Listbox.font', (THEME["font_family"], THEME["font_size"]))
        self.option_add('*TCombobox*Listbox.relief', 'flat')
        self.option_add('*TCombobox*Listbox.borderwidth', '0')
        
        # Bind hover events
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        
    def _on_enter(self, event):
        self.state(['active'])
        
    def _on_leave(self, event):
        self.state(['!active'])