from pathlib import Path
import json


class Settings:
    """Easy 'settings' thingybob that will prompt the user to set values via GUI if anything un-set tries to get referenced."""

    def __init__(self, 
                 schema: dict, 
                 save_file: Path, 
                 settings_screen_title: str,
                 gui_theme: str = "Reddit"):
        self.settings_screen_title = settings_screen_title
        self.gui_theme = gui_theme
        self._schema = schema
        self._values = dict()
        self.save_file = save_file
        self.load()

    def load(self):
        if self.save_file.exists():
            with open(self.save_file, "r") as f:
                self._values = json.load(f)

    def save(self):
        with open(self.save_file, "w") as f:
            json.dump(self._values, f)
    
    def __getitem__(self, key: str):
        if key not in self._values.keys():
            self.prompt()

        return self._values[key]
    
    def prompt(self):
        from gui.popups import SettingsDialog  # local import: utils/ stays import-light, gui/ is the only consumer
        dialog = SettingsDialog(schema=self._schema, values=self._values, title=self.settings_screen_title)
        if dialog.exec():
            for key, value in dialog.values().items():
                if value not in ("", None):
                    self[key] = value

    def __setitem__(self, key: str, value):
        self._values[key] = value
        self.save()

    def set_default(self, key: str, value) -> None:
        """Ensures `key` has a value, without prompting: sets `value` only if the
        key is currently unset, so callers can read it with __getitem__ right away."""
        if key not in self._values:
            self[key] = value
