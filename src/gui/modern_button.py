import tkinter as tk
from tkinter import ttk

class ModernButton(ttk.Button):
    def __init__(self, master=None, **kw):
        super().__init__(master, style="Modern.TButton", **kw)