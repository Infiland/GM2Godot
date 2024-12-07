import tkinter as tk
from tkinter import ttk
import requests
import webbrowser
from PIL import Image, ImageTk
from io import BytesIO
from datetime import datetime
from src.version import get_version

class AboutDialog:
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("About GM2Godot")
        self.dialog.geometry("600x700")
        self.dialog.configure(bg="#222222")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self.style = ttk.Style()
        self.setup_styles()
        self.create_widgets()
        
    def setup_styles(self):
        """Configure styles for the About dialog."""
        styles = {
            "About.TFrame": {"background": "#222222"},
            "About.TLabel": {
                "background": "#222222",
                "foreground": "#ffffff",
                "font": ('Helvetica', 10)
            },
            "AboutTitle.TLabel": {
                "background": "#222222",
                "foreground": "#ffffff",
                "font": ('Helvetica', 16, 'bold')
            },
            "AboutSection.TLabel": {
                "background": "#222222",
                "foreground": "#ffffff",
                "font": ('Helvetica', 12, 'bold')
            }
        }
        for style, options in styles.items():
            self.style.configure(style, **options)
                           
    def create_widgets(self):
        """Create and layout all widgets in the About dialog."""
        main_frame = ttk.Frame(self.dialog, style="About.TFrame", padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, 
                 text=f"GM2Godot v{get_version()}", 
                 style="AboutTitle.TLabel").pack(pady=(0, 10))
        
        description = (
            "GM2Godot is a tool designed to help developers migrate their "
            "GameMaker projects to the Godot Engine. It automates the conversion "
            "of various project assets and settings, making the transition smoother."
        )
        ttk.Label(main_frame, 
                 text=description, 
                 style="About.TLabel", 
                 wraplength=500).pack(pady=(0, 20))
        
        ttk.Label(main_frame, 
                 text="Contributors", 
                 style="AboutSection.TLabel").pack(pady=(0, 10))
        
        self.create_contributors_list(main_frame)
        self.create_links_section(main_frame)
        
        # Copyright
        self.create_copyright_label(main_frame)
    
    def create_contributors_list(self, parent):
        """Create scrollable contributors list."""
        contributors_frame = ttk.Frame(parent, style="About.TFrame")
        contributors_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(contributors_frame, 
                         bg="#222222", 
                         highlightthickness=0)
        scrollbar = ttk.Scrollbar(contributors_frame, 
                                orient="vertical", 
                                command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style="About.TFrame")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), 
                           window=scrollable_frame, 
                           anchor="nw", 
                           width=500)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.display_contributors(scrollable_frame)
    
    def create_links_section(self, parent):
        """Create links section with clickable links."""
        links_frame = ttk.Frame(parent, style="About.TFrame")
        links_frame.pack(pady=20)
        
        links = [
            ("GitHub Repository", "https://github.com/Infiland/GM2Godot"),
            ("Report an Issue", "https://github.com/Infiland/GM2Godot/issues"),
            ("Infiland Website", "https://infi.land")
        ]
        
        for text, url in links:
            link = ttk.Label(links_frame, 
                           text=text,
                           style="About.TLabel",
                           cursor="hand2")
            link.pack(pady=2)
            link.bind("<Button-1>", lambda e, url=url: webbrowser.open_new(url))
    
    def create_copyright_label(self, parent):
        """Create copyright label with current year."""
        current_year = datetime.now().year
        copyright_text = f"© {current_year} Infiland. All rights reserved."
        ttk.Label(parent, 
                 text=copyright_text,
                 style="About.TLabel").pack(pady=(20, 0))
                 
    def display_contributors(self, parent_frame):
        """Fetch and display GitHub contributors."""
        try:
            response = requests.get(
                "https://api.github.com/repos/Infiland/GM2Godot/contributors",
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            response.raise_for_status()
            contributors = response.json()
            
            for contributor in contributors:
                self.create_contributor_widget(parent_frame, contributor)
                
        except Exception as e:
            ttk.Label(parent_frame,
                     text=f"Failed to load contributors: {str(e)}",
                     style="About.TLabel").pack(pady=5)
                     
    def create_contributor_widget(self, parent_frame, contributor):
        """Create a widget for a single contributor."""
        contributor_frame = ttk.Frame(parent_frame, style="About.TFrame")
        contributor_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # Try to load avatar
        try:
            response = requests.get(contributor['avatar_url'])
            image = Image.open(BytesIO(response.content))
            image = image.resize((40, 40), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            
            avatar_label = ttk.Label(contributor_frame, 
                                   image=photo, 
                                   style="About.TLabel")
            avatar_label.image = photo  # Keep a reference
            avatar_label.pack(side=tk.LEFT, padx=(0, 10))
        except:
            # If avatar loading fails, skip it
            pass
            
        info_frame = ttk.Frame(contributor_frame, style="About.TFrame")
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        name_label = ttk.Label(info_frame,
                             text=contributor['login'],
                             style="About.TLabel",
                             cursor="hand2")
        name_label.pack(anchor="w")
        name_label.bind("<Button-1>", 
                       lambda e, url=contributor['html_url']: webbrowser.open_new(url))
        
        contributions = f"{contributor['contributions']} contributions"
        ttk.Label(info_frame,
                 text=contributions,
                 style="About.TLabel").pack(anchor="w")