class SettingValue:
    """Drop-in replacement for tk.BooleanVar, compatible with converter.py's .get() interface."""

    def __init__(self, value=True):
        self._value = bool(value)

    def get(self):
        return self._value

    def set(self, value):
        self._value = bool(value)
