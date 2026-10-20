import pytest

from scheduler.config import ALL_DAYS, WEEKDAYS, ConfigError, load_config


def test_real_config_loads():
    settings = load_config()
    assert settings.briefings, "config.yaml should define at least one briefing"
    for b in settings.briefings:
        assert b.prompt_file.exists()
        assert b.prompt().strip()


def _write(tmp_path, briefing_yaml, extra=""):
    (tmp_path / "p.md").write_text("Write a briefing.")
    path = tmp_path / "config.yaml"
    path.write_text(f"timezone: Asia/Kolkata\n{extra}briefings:\n{briefing_yaml}")
    return path


def test_days_and_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("scheduler.config.ROOT", tmp_path)
    path = _write(tmp_path, '  - id: a\n    prompt_file: p.md\n    time: "07:00"\n    days: weekdays\n'
                            '  - id: b\n    prompt_file: p.md\n    time: "08:00"\n    days: [Mon, fri]\n'
                            '  - id: c\n    prompt_file: p.md\n    time: "09:00"\n',
                  extra="defaults:\n  model: gemini-4-argon\n  effort: low\n")
    a, b, c = load_config(path).briefings
    assert a.days == WEEKDAYS and b.days == ["mon", "fri"] and c.days == ALL_DAYS
    assert c.model == "gemini-4-argon" and c.effort == "low"


@pytest.mark.parametrize("briefing, message", [
    ('  - id: a\n    prompt_file: p.md\n    time: "7:00"\n', "time"),
    ('  - id: A b\n    prompt_file: p.md\n    time: "07:00"\n', "id"),
    ('  - id: a\n    prompt_file: missing.md\n    time: "07:00"\n', "prompt file"),
    ('  - id: a\n    prompt_file: p.md\n    time: "07:00"\n    deliver: [sms]\n', "deliver"),
    ('  - id: a\n    prompt_file: p.md\n    time: "07:00"\n    effort: max\n', "effort"),
    ('  - id: a\n    prompt_file: p.md\n    time: "07:00"\n    days: [funday]\n', "day"),
])
def test_bad_config_is_explained(tmp_path, monkeypatch, briefing, message):
    monkeypatch.setattr("scheduler.config.ROOT", tmp_path)
    with pytest.raises(ConfigError, match=message):
        load_config(_write(tmp_path, briefing))
