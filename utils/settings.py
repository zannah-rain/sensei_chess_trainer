from pathlib import Path
import json
import PySimpleGUI as sg


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
    
    @staticmethod
    def schema_input_type_mapping(input_name: str, input_type: str, current_value):
        if type(input_type) == list:
            return [sg.Push(), sg.Text(input_name), sg.Listbox(input_type, key=input_name, default_values=current_value)]
        elif input_type == "str":
            return [sg.Push(), sg.Text(input_name), sg.InputText(key=input_name, default_text=current_value)]
        elif input_type == "Path":
            return [sg.Push(), sg.Text(input_name), sg.FileBrowse(key=input_name, initial_folder=current_value)]
        elif input_type == "bool":
            return [sg.Push(), sg.Text(input_name), sg.Checkbox(key=input_name, default=current_value)]
        else:
            raise NotImplementedError()
    
    def prompt_layout(self):
        sg.ChangeLookAndFeel(self.gui_theme)
        sg.SetOptions(margins=(0, 3), border_width=1)

        layout = [
            [sg.Text(self.settings_screen_title)]
        ]

        for k, v in sorted(self._schema.items()):
            if k in self._values.keys():
                current_value = self._values[k]
            else:
                current_value = None
            layout.append(self.schema_input_type_mapping(k, v, current_value))

        layout.append([sg.Submit()])

        return layout
    
    def prompt(self):
        event, values = sg.Window(title=self.settings_screen_title,
                                  layout=self.prompt_layout(),
                                  no_titlebar=True).read(close=True)
        for k, v in values.items():
            input_type = self._schema[k]
            if type(input_type) == list:
                if len(v) == 1:
                    self[k] = v[0]
            elif input_type == "str":
                if v != "":
                    self[k] = v
            elif input_type == "Path":
                if v != "":
                    self[k] = v
            else:
                raise NotImplementedError()

    def __setitem__(self, key: str, value):
        self._values[key] = value
        self.save()
