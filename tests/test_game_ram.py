import pytest

from core import game_ram, validator


@pytest.mark.parametrize(
    ("value", "mb"), [("8g", 8192), ("12G", 12288), ("512m", 512), ("16", 16384), ("junk", 8192)]
)
def test_mem_limit_mb(value, mb):
    assert game_ram.mem_limit_mb(value) == mb


def test_get_and_set_preserve_other_lines(tmp_path):
    props = tmp_path / "tlauncher-2.0.properties"
    props.write_text("# Version\nlocale1=en\nminecraft.memory.ram3=5461\nminecraft.size=925;530\n")
    assert game_ram.get_game_ram(props) == 5461
    game_ram.set_game_ram(4096, props)
    assert game_ram.get_game_ram(props) == 4096
    text = props.read_text()
    assert "locale1=en" in text and "minecraft.size=925;530" in text and text.count("ram3") == 1


def test_get_missing_file_and_key(tmp_path):
    assert game_ram.get_game_ram(tmp_path / "nope") is None
    props = tmp_path / "p"
    props.write_text("locale1=en\n")
    assert game_ram.get_game_ram(props) is None
    game_ram.set_game_ram(3000, props)
    assert game_ram.get_game_ram(props) == 3000


@pytest.mark.parametrize(
    ("current", "cap", "mods", "expected"),
    [
        (None, 8192, 12, 4096),  # never set -> modpack default
        (2048, 8192, 12, 4096),  # too little for a modpack
        (5461, 8192, 12, None),  # already plenty and fits
        (7900, 8192, 12, 4096),  # doesn't fit the cap
        (2048, 4096, 12, 2560),  # small cap -> capped suggestion
        (4096, 16384, 120, 6144),  # big pack wants more
    ],
)
def test_suggest_for_modpack(current, cap, mods, expected):
    assert game_ram.suggest_for_modpack(current, cap, mods) == expected


def test_validator_flags_ram_above_cap(monkeypatch):
    monkeypatch.setattr(game_ram, "get_game_ram", lambda *_: 8000)
    (issue,) = validator._check_game_ram({"memory": "8g"})
    assert issue.code == validator.GAME_RAM_TOO_HIGH
    assert "game-ram 6656" in issue.fix_hint
    monkeypatch.setattr(game_ram, "get_game_ram", lambda *_: 4096)
    assert validator._check_game_ram({"memory": "8g"}) == []
    monkeypatch.setattr(game_ram, "get_game_ram", lambda *_: None)
    assert validator._check_game_ram({"memory": "8g"}) == []
