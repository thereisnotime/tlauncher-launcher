import pytest

from core import config


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg" / "minecraft-launcher"
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_dir / "config.yaml")
    return cfg_dir / "config.yaml"


def test_load_missing_returns_empty(cfg_file):
    assert not cfg_file.exists()
    assert config.load_config() == {}
    assert not config.config_exists()


def test_save_load_round_trip(cfg_file):
    data = {
        "runtime": "docker",
        "gpu": "nvidia",
        "display": "wayland",
        "audio": "none",
        "java": "25",
        "memory": "12g",
        "auto_xhost": False,
    }
    assert config.save_config(data)
    assert cfg_file.is_file()
    assert config.config_exists()
    assert config.get_config_path() == cfg_file
    assert config.load_config() == data


def test_save_drops_unknown_keys_and_fills_defaults(cfg_file):
    assert config.save_config({"gpu": "amd", "bogus": "x"})
    loaded = config.load_config()
    assert loaded == {
        "runtime": "",
        "gpu": "amd",
        "display": "",
        "audio": "",
        "java": "",
        "memory": "",
        "auto_xhost": True,
    }


def test_load_partial_file_fills_defaults(cfg_file):
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("gpu: intel\n")
    loaded = config.load_config()
    assert loaded["gpu"] == "intel"
    assert loaded["runtime"] == ""
    assert loaded["auto_xhost"] is True


def test_load_empty_file_gives_defaults(cfg_file):
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("")
    loaded = config.load_config()
    assert loaded["runtime"] == ""
    assert loaded["auto_xhost"] is True


@pytest.mark.parametrize("content", ["runtime: [unclosed\n", "- just\n- a list\n"])
def test_load_broken_file_is_ignored(cfg_file, content):
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text(content)
    assert config.load_config() == {}


def test_reset_config(cfg_file):
    config.save_config({"gpu": "amd"})
    assert config.reset_config()
    assert not cfg_file.exists()
    assert config.reset_config()  # already gone is fine


DETECTED = {"runtime": "podman", "gpu": "amd", "display": "x11", "audio": "pulseaudio"}


def test_merge_saved_overrides_detected():
    saved = {"runtime": "docker", "gpu": "nvidia", "display": "wayland", "audio": "none"}
    merged = config.merge_config(DETECTED, saved)
    for key in ("runtime", "gpu", "display", "audio"):
        assert merged[key] == saved[key]


def test_merge_blank_saved_values_keep_detected():
    saved = {"runtime": "", "gpu": "   ", "display": None}
    merged = config.merge_config(DETECTED, saved)
    for key in ("runtime", "gpu", "display", "audio"):
        assert merged[key] == DETECTED[key]


def test_merge_defaults_and_does_not_mutate_detected():
    detected = dict(DETECTED)
    merged = config.merge_config(detected, {})
    assert detected == DETECTED
    assert merged["java"] == config.DEFAULT_JAVA
    assert merged["memory"] == config.DEFAULT_MEMORY
    assert merged["auto_xhost"] is True


def test_merge_normalises_java_memory_and_keeps_auto_xhost():
    merged = config.merge_config(DETECTED, {"java": "25", "memory": "16", "auto_xhost": False})
    assert merged["java"] == "25"
    assert merged["memory"] == "16g"
    assert merged["auto_xhost"] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("21", "21"),
        ("25", "25"),
        (25, "25"),
        (" 25 ", "25"),
        ("17", "21"),
        ("", "21"),
        (None, "21"),
        ("java25", "21"),
    ],
)
def test_normalize_java(value, expected):
    assert config.normalize_java(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("8g", "8g"),
        ("4g", "4g"),
        ("16G", "16g"),
        (" 6g ", "6g"),
        ("12", "12g"),
        (12, "12g"),
        ("3g", "8g"),
        ("8gb", "8g"),
        ("", "8g"),
        (None, "8g"),
        ("lots", "8g"),
    ],
)
def test_normalize_memory(value, expected):
    assert config.normalize_memory(value) == expected


def test_default_config_text_parses_and_covers_every_key(tmp_path, monkeypatch):
    import yaml

    from core import config as cfgmod

    data = yaml.safe_load(cfgmod.default_config_text())
    assert set(data) == set(cfgmod.create_default_config())
    f = tmp_path / "config.yaml"
    f.write_text(cfgmod.default_config_text())
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", f)
    merged = cfgmod.merge_config({"runtime": "podman"}, cfgmod.load_config())
    assert merged["java"] == cfgmod.DEFAULT_JAVA
    assert merged["memory"] == cfgmod.DEFAULT_MEMORY
