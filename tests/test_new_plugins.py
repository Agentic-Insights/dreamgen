import json
from datetime import datetime
from unittest.mock import mock_open

from src.plugins.holiday_fact import HolidayFact, get_holiday_fact
from src.plugins.nearest_holiday import get_nearest_holiday
from src.plugins.time_of_day import get_time_of_day


class FixedDatetime(datetime):
    """Helper datetime class for controlling now()."""

    @classmethod
    def now(cls):  # type: ignore[override]
        return cls(2024, 12, 1)


def test_get_time_of_day_evening(monkeypatch):
    class EveningDatetime(datetime):
        @classmethod
        def now(cls):  # type: ignore[override]
            return cls(2024, 1, 1, 18, 0, 0)

    monkeypatch.setattr("src.plugins.time_of_day.datetime", EveningDatetime)
    assert get_time_of_day() == "evening"


def test_get_nearest_holiday(monkeypatch):
    holidays = [
        {"month": 12, "day": 25, "name": "Christmas"},
        {"month": 1, "day": 1, "name": "New Year's Day"},
    ]
    m = mock_open(read_data=json.dumps(holidays))
    monkeypatch.setattr("builtins.open", m)
    monkeypatch.setattr("src.plugins.nearest_holiday.datetime", FixedDatetime)
    assert get_nearest_holiday() == "approaching Christmas"


def test_get_holiday_fact_fun(monkeypatch):
    HolidayFact._instance = None
    plugin = HolidayFact()
    monkeypatch.setattr(
        plugin,
        "get_todays_holidays",
        lambda: [
            {
                "month": 12,
                "day": 1,
                "name": "Test Day",
                "type": "fun",
            }
        ],
    )
    HolidayFact._instance = plugin
    assert "Test Day" in get_holiday_fact()
