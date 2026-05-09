class SettingValue:
    """Drop-in replacement for tk.BooleanVar, compatible with converter.py's .get() interface."""

    def __init__(self, value: bool = True) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
