from utils.settings import Settings


def new_settings(save_file, **overrides):
    defaults = {
        "schema": {"Stockfish Executable": "Path"},
        "save_file": save_file,
        "settings_screen_title": "Test Settings:",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_a_key_already_present_in_the_save_file_loads_without_prompting(tmp_path):
    # Given a save file that already has a value for a schema key
    save_file = tmp_path / "settings.json"
    save_file.write_text('{"Stockfish Executable": "C:/engines/stockfish.exe"}')
    settings = new_settings(save_file)
    settings.prompt = lambda: (_ for _ in ()).throw(AssertionError("prompt() should not be called"))

    # When reading that key
    value = settings["Stockfish Executable"]

    # Then it's read straight from the save file, with no prompt
    assert value == "C:/engines/stockfish.exe"


def test_setting_a_value_persists_to_the_save_file_for_a_fresh_instance_to_read(tmp_path):
    # Given a brand new settings file with nothing in it yet
    save_file = tmp_path / "settings.json"
    first_settings = new_settings(save_file)

    # When setting a value on that instance
    first_settings["Stockfish Executable"] = "C:/engines/stockfish.exe"

    # Then a completely separate instance pointed at the same file reads it back
    second_settings = new_settings(save_file)
    assert second_settings["Stockfish Executable"] == "C:/engines/stockfish.exe"


def test_a_missing_key_triggers_a_prompt(tmp_path):
    # Given a settings file with no value for the schema key
    save_file = tmp_path / "settings.json"
    settings = new_settings(save_file)
    prompts = []
    settings.prompt = lambda: prompts.append(1)

    # When reading that key (prompt() is stubbed to do nothing, so this would
    # normally then raise - the point here is only whether prompt() got called)
    try:
        settings["Stockfish Executable"]
    except KeyError:
        pass

    # Then the missing value triggered exactly one prompt
    assert prompts == [1]
