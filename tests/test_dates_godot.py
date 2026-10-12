"""GameMaker's date functions give the HTML5 runner's values in a converted game.

The reference below ports functions/Function_Date.js from the GameMaker HTML5
runner, with JavaScript's Date semantics (TimeClip, MakeDay, MakeTime and the
local time zone's offset at each instant, an ambiguous local time taking the
earlier instant and a skipped one the offset before the transition). Each
case runs in Godot with TZ set to a zone, in local time and again after
date_set_timezone(timezone_utc), and is compared with the reference in the
same zone.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from src.conversion.gml_runtime import write_gml_runtime
from src.conversion.gml_transpiler import transpile_gml_expression
from tests.godot_test_support import find_smoke_godot_binary, write_fixture_text

_RESULT_PREFIX = "DATE_RESULT "
_MS_PER_DAY = 86400000.0
_DAYS_SINCE_1900 = 25569.0
_NAN = float("nan")


def _int32(value: float) -> int:
    if math.isnan(value) or math.isinf(value):
        return 0
    wrapped = int(math.trunc(value)) % 2**32
    return wrapped - 2**32 if wrapped >= 2**31 else wrapped


def _time_clip(value: float) -> float:
    if math.isnan(value) or math.isinf(value) or abs(value) > 8.64e15:
        return _NAN
    return float(math.trunc(value))


def _days_from_civil(year: int, month: int, day: int) -> int:
    return (date(2000, 1, 1) - date(1970, 1, 1)).days + (
        _gregorian_ordinal(year, month, day) - _gregorian_ordinal(2000, 1, 1)
    )


def _gregorian_ordinal(year: int, month: int, day: int) -> int:
    # Proleptic Gregorian day count that also works outside datetime's years.
    y = year - (1 if month <= 2 else 0)
    era = y // 400
    year_of_era = y - era * 400
    day_of_year = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5 + day - 1
    return era * 146097 + year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year


def _make_day(year: float, month: float, day: float) -> float:
    if any(math.isnan(v) or math.isinf(v) for v in (year, month, day)):
        return _NAN
    whole_year = math.trunc(year) + math.floor(math.trunc(month) / 12)
    whole_month = math.trunc(month) % 12
    return float(_days_from_civil(whole_year, whole_month + 1, 1)) + math.trunc(day) - 1


def _make_time(hour: float, minute: float, second: float, ms: float) -> float:
    return hour * 3600000.0 + minute * 60000.0 + second * 1000.0 + ms


def _make_date(day: float, clock: float) -> float:
    value = day * _MS_PER_DAY + clock
    return _NAN if math.isnan(value) or math.isinf(value) else value


class _PosixRules(tzinfo):
    """A POSIX TZ string's M rules, such as TZ="EST5EDT,M3.2.0,M11.1.0".

    Each rule is (month, week, weekday, seconds after local midnight in the
    offset in effect before the change); week 5 means the last such weekday.
    """

    def __init__(self, standard_hours: float, daylight_hours: float, start: tuple[int, int, int, int],
                 end: tuple[int, int, int, int]) -> None:
        self.standard = timedelta(hours=standard_hours)
        self.daylight = timedelta(hours=daylight_hours)
        self.start = start
        self.end = end

    @staticmethod
    def _local_change(year: int, rule: tuple[int, int, int, int]) -> datetime:
        month, week, weekday, seconds = rule
        day = 1 + (weekday - (date(year, month, 1).weekday() + 1)) % 7 + (week - 1) * 7
        next_month = date(year + month // 12, month % 12 + 1, 1)
        while day > (next_month - date(year, month, 1)).days:
            day -= 7
        return datetime(year, month, day) + timedelta(seconds=seconds)

    def _daylight_at(self, utc: datetime) -> bool:
        start = self._local_change(utc.year, self.start) - self.standard
        end = self._local_change(utc.year, self.end) - self.daylight
        if start < end:
            return start <= utc < end
        return not end <= utc < start

    def fromutc(self, dt: datetime) -> datetime:
        utc = dt.replace(tzinfo=None)
        daylight = self._daylight_at(utc)
        local = utc + (self.daylight if daylight else self.standard)
        # The later of two instants with the same local time has fold=1.
        fold = int(not daylight and self._daylight_at(local - self.daylight))
        return local.replace(tzinfo=self, fold=fold)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        local = dt.replace(tzinfo=None)
        daylight_fits = self._daylight_at(local - self.daylight)
        standard_fits = not self._daylight_at(local - self.standard)
        if daylight_fits and standard_fits:  # Repeated: fold=0 is the earlier.
            return self.standard if dt.fold else self.daylight
        if daylight_fits or standard_fits:
            return self.daylight if daylight_fits else self.standard
        return self.daylight if dt.fold else self.standard  # Skipped: the offset before.

    def dst(self, dt: datetime | None) -> timedelta:
        return self.utcoffset(dt) - self.standard

    def tzname(self, dt: datetime | None) -> str:
        return "posix"


class _JSDate:
    """The JavaScript Date operations the runner uses, in one time zone."""

    def __init__(self, zone: tzinfo, utc_mode: bool) -> None:
        self.zone = zone
        self.local = not utc_mode

    def offset(self, t: float) -> float:
        moment = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=math.floor(t / 1000))
        offset = moment.astimezone(self.zone).utcoffset()
        assert offset is not None
        return offset.total_seconds() * 1000.0

    def utc(self, local_time: float) -> float:
        if math.isnan(local_time):
            return _NAN
        naive = datetime(1970, 1, 1) + timedelta(milliseconds=local_time)
        offset = naive.replace(tzinfo=self.zone, fold=0).utcoffset()
        assert offset is not None
        return local_time - offset.total_seconds() * 1000.0

    def fields(self, t: float, local: bool | None = None) -> dict[str, int] | None:
        if math.isnan(t):
            return None
        use_local = self.local if local is None else local
        moment = t + (self.offset(t) if use_local else 0.0)
        day_number = math.floor(moment / _MS_PER_DAY)
        in_day = int(moment - day_number * _MS_PER_DAY)
        civil = date(1970, 1, 1) + timedelta(days=day_number)
        return {
            "year": civil.year,
            "month": civil.month - 1,
            "day": civil.day,
            "weekday": (day_number + 4) % 7,
            "hour": in_day // 3600000,
            "minute": in_day // 60000 % 60,
            "second": in_day // 1000 % 60,
            "millisecond": in_day % 1000,
        }


def _time_of_datetime(value: float) -> float:
    if value < _DAYS_SINCE_1900:
        return _time_clip(value * _MS_PER_DAY)
    return _time_clip((value - _DAYS_SINCE_1900) * _MS_PER_DAY)


def _month_lengths(year: int) -> list[int]:
    leap = year % 400 == 0 or (year % 100 != 0 and year % 4 == 0)
    return [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


class _Runner:
    """Function_Date.js."""

    def __init__(self, js: _JSDate, now: float) -> None:
        self.js = js
        self.now = now

    def create_datetime(self, *values: float) -> float:
        year, month, day, hour, minute, second = (_int32(v) for v in values)
        js = self.js
        day_value = _make_day(year, month - 1, day)
        clock = _make_time(hour, minute, second, 10)
        if js.local:
            local_now = self.now + js.offset(self.now)
            t = _time_clip(js.utc(_make_date(day_value, local_now % _MS_PER_DAY)))
            if not math.isnan(t):
                local = t + js.offset(t)
                t = _time_clip(js.utc(_make_date(math.floor(local / _MS_PER_DAY), clock)))
        else:
            t = _time_clip(_make_date(day_value, self.now % _MS_PER_DAY))
            if not math.isnan(t):
                t = _time_clip(_make_date(math.floor(t / _MS_PER_DAY), clock))
        return t / _MS_PER_DAY + _DAYS_SINCE_1900

    def fields(self, value: float, local: bool | None = None) -> dict[str, int] | None:
        return self.js.fields(_time_of_datetime(value), local)

    def field(self, value: float, name: str) -> float:
        fields = self.fields(value)
        return _NAN if fields is None else fields[name]

    def month_lengths(self, value: float) -> tuple[list[int], int]:
        """The month lengths of the value's year and its month (0-11)."""
        fields = self.fields(value)
        assert fields is not None
        return _month_lengths(fields["year"]), fields["month"]

    def day_of_year(self, value: float) -> float:
        fields = self.fields(value)
        if fields is None:
            return _NAN
        return sum(_month_lengths(fields["year"])[: fields["month"]]) + fields["day"]

    def inc_day_fields(self, value: float, years: int, months: int, days: int) -> float:
        t = _time_of_datetime(value)
        fields = self.js.fields(t, False)
        if fields is None:
            return _NAN
        day_value = _make_day(fields["year"] + years, fields["month"] + months, fields["day"] + days)
        return _time_clip(_make_date(day_value, t % _MS_PER_DAY)) / _MS_PER_DAY + _DAYS_SINCE_1900

    def inc_clock_fields(self, value: float, hours: int, minutes: int, seconds: int) -> float:
        t = _time_of_datetime(value)
        fields = self.js.fields(t, False)
        if fields is None:
            return _NAN
        clock = _make_time(fields["hour"] + hours, fields["minute"] + minutes, fields["second"] + seconds, fields["millisecond"])
        return _time_clip(_make_date(math.floor(t / _MS_PER_DAY), clock)) / _MS_PER_DAY + _DAYS_SINCE_1900

    def span(self, first: float, second: float, *divisors: float) -> float:
        value = float(math.floor((_time_of_datetime(second) - _time_of_datetime(first)) / 1000))
        for divisor in divisors:
            value /= divisor
        return abs(value)

    def compare(self, first: float, second: float, part: str) -> float:
        a, b = self.fields(first, True), self.fields(second, True)
        if part == "date":
            values = [None if f is None else f["year"] * 366 + f["month"] * 31 + f["day"] for f in (a, b)]
        else:
            values = [None if f is None else f["hour"] * 3600 + f["minute"] * 60 + f["second"] for f in (a, b)]
        if values[0] is None or values[1] is None or values[0] < values[1]:
            return -1.0 if values[0] != values[1] or values[0] is None else 0.0
        return 0.0 if values[0] == values[1] else 1.0

    def date_of(self, value: float) -> float:
        t = _time_clip((value - _DAYS_SINCE_1900) * 86400.0 * 1000.0)
        fields = self.js.fields(t)
        if fields is None:
            return _NAN
        year = fields["year"] + 1900 if 0 <= fields["year"] <= 99 else fields["year"]
        midnight = _time_clip(self.js.utc(_make_date(_make_day(year, fields["month"], fields["day"]), 0.0)))
        seconds = midnight / 1000.0
        if not self.js.local:
            seconds -= ((midnight - (midnight + self.js.offset(midnight))) / 60000.0) * 60.0
        return ((seconds + 0.5) / 86400.0) + _DAYS_SINCE_1900

    def text(self, value: float, with_date: bool, with_clock: bool) -> str:
        fields = self.fields(value)
        if fields is None:
            return "invalid time" if not with_date else ("NaN/NaN/NaN NaN:NaN:NaN" if with_clock else "NaN/NaN/NaN")

        def pad(number: int) -> str:
            return f"0{number}" if number < 10 else str(number)

        parts: list[str] = []
        if with_date:
            parts.append(f"{pad(fields['day'])}/{pad(fields['month'] + 1)}/{fields['year']}")
        if with_clock:
            parts.append(f"{pad(fields['hour'])}:{pad(fields['minute'])}:{pad(fields['second'])}")
        return " ".join(parts)

    def valid(self, *values: float) -> int:
        y, m, d, h, mi, s = (_int32(v) for v in values)
        if not (y >= 1970 and 1 <= m <= 12 and 1 <= d <= 31 and 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
            return 0
        return 0 if d > _month_lengths(y)[m - 1] else 1


# GML for each datetime the cases use, with the arguments to create it.
_CREATED: tuple[tuple[int, ...], ...] = (
    (2018, 9, 3, 15, 30, 27),
    (2021, 3, 14, 2, 30, 0),
    (2021, 11, 7, 1, 30, 0),
    (2024, 2, 29, 23, 59, 59),
    (2022, 4, 17, 0, 0, 0),
    (2023, 13, 32, 25, 61, 61),
    (1969, 12, 31, 12, 0, 0),
    (2021, 10, 3, 2, 30, 0),
    (2021, 4, 4, 2, 30, 0),
    (2026, 1, 1, 24, 0, 0),
)
_RAW_VALUES = (45000.75, 44000.123456, 25569.0, 20000.5, 46000.999999)


def _cases(runner: _Runner) -> list[tuple[str, object]]:
    datetimes: list[tuple[str, float]] = [
        (f"date_create_datetime({', '.join(str(v) for v in args)})", runner.create_datetime(*args)) for args in _CREATED
    ]
    datetimes += [(repr(value), value) for value in _RAW_VALUES]
    cases: list[tuple[str, object]] = [(gml, value) for gml, value in datetimes[: len(_CREATED)]]
    for gml, value in datetimes:
        lengths, month = runner.month_lengths(value)
        cases += [
            (f"date_get_year({gml})", runner.field(value, "year")),
            (f"date_get_month({gml})", runner.field(value, "month") + 1),
            (f"date_get_day({gml})", runner.field(value, "day")),
            (f"date_get_weekday({gml})", runner.field(value, "weekday")),
            (f"date_get_hour({gml})", runner.field(value, "hour")),
            (f"date_get_minute({gml})", runner.field(value, "minute")),
            (f"date_get_second({gml})", runner.field(value, "second")),
            (f"date_get_week({gml})", math.floor(runner.day_of_year(value) / 7)),
            (f"date_get_day_of_year({gml})", runner.day_of_year(value)),
            (f"date_get_hour_of_year({gml})", (runner.day_of_year(value) - 1) * 24 + runner.field(value, "hour")),
            (
                f"date_get_minute_of_year({gml})",
                (runner.day_of_year(value) - 1) * 24 * 60 + runner.field(value, "hour") * 60 + runner.field(value, "minute"),
            ),
            (
                f"date_get_second_of_year({gml})",
                (runner.day_of_year(value) - 1) * 86400
                + runner.field(value, "hour") * 3600
                + runner.field(value, "minute") * 60
                + runner.field(value, "second"),
            ),
            (f"date_datetime_string({gml})", runner.text(value, True, True)),
            (f"date_date_string({gml})", runner.text(value, True, False)),
            (f"date_time_string({gml})", runner.text(value, False, True)),
            (f"date_days_in_month({gml})", lengths[month]),
            (f"date_days_in_year({gml})", sum(lengths)),
            (f"date_leap_year({gml})", lengths[1] == 29),
            (f"date_date_of({gml})", runner.date_of(value)),
            (f"date_time_of({gml})", value - _int32(value)),
        ]
        for amount in (1, -1, 13):
            cases += [
                (f"date_inc_year({gml}, {amount})", runner.inc_day_fields(value, amount, 0, 0)),
                (f"date_inc_month({gml}, {amount})", runner.inc_day_fields(value, 0, amount, 0)),
                (f"date_inc_week({gml}, {amount})", runner.inc_day_fields(value, 0, 0, amount * 7)),
                (f"date_inc_day({gml}, {amount})", runner.inc_day_fields(value, 0, 0, amount)),
                (f"date_inc_hour({gml}, {amount})", runner.inc_clock_fields(value, amount, 0, 0)),
                (f"date_inc_minute({gml}, {amount})", runner.inc_clock_fields(value, 0, amount, 0)),
                (f"date_inc_second({gml}, {amount})", runner.inc_clock_fields(value, 0, 0, amount)),
            ]
    for (gml1, value1), (gml2, value2) in zip(datetimes, datetimes[1:] + datetimes[:1], strict=True):
        pair = f"{gml1}, {gml2}"
        cases += [
            (f"date_year_span({pair})", runner.span(value1, value2, 60, 60, 24, 365.25)),
            (f"date_month_span({pair})", runner.span(value1, value2, 60, 60, 24, 30.4375)),
            (f"date_week_span({pair})", runner.span(value1, value2, 60, 60, 24, 7)),
            (f"date_day_span({pair})", runner.span(value1, value2, 60, 60, 24)),
            (f"date_hour_span({pair})", runner.span(value1, value2, 60, 60)),
            (f"date_minute_span({pair})", runner.span(value1, value2, 60)),
            (f"date_second_span({pair})", _int32(runner.span(value1, value2))),
            (f"date_compare_datetime({pair})", (value1 > value2) - (value1 < value2)),
            (f"date_compare_date({pair})", runner.compare(value1, value2, "date")),
            (f"date_compare_time({pair})", runner.compare(value1, value2, "time")),
        ]
    for args in ((2024, 2, 29, 0, 0, 0), (2023, 2, 29, 0, 0, 0), (1969, 1, 1, 0, 0, 0), (2020, 4, 31, 0, 0, 0),
                 (2020, 12, 31, 23, 59, 59), (2020, 1, 1, 24, 0, 0), (2020.9, 1.5, 1.2, 0, 0, 0)):
        cases.append((f"date_valid_datetime({', '.join(str(v) for v in args)})", runner.valid(*args)))
    cases += [
        ("date_get_year(NaN)", _NAN),
        ("date_datetime_string(NaN)", "NaN/NaN/NaN NaN:NaN:NaN"),
        ("date_time_string(NaN)", "invalid time"),
        ("date_days_in_year(NaN)", 365),
        ("date_leap_year(NaN)", False),
        ("date_inc_day(NaN, 1)", _NAN),
        ("date_second_span(NaN, 1)", 0),
        ("date_get_timezone()", 0 if runner.js.local else 1),
    ]
    return cases


def _probe_script(local_cases: list[tuple[str, object]], utc_cases: list[tuple[str, object]]) -> str:
    def block(cases: list[tuple[str, object]]) -> str:
        return "".join(f"\t\t_encode({transpile_gml_expression(gml)}),\n" for gml, _ in cases)

    return (
        "extends Node\n\n"
        'const GMRuntime = preload("res://gm2godot/gml_runtime.gd")\n\n'
        "var other = null\n\n\n"
        "func _encode(value):\n"
        "\tif typeof(value) == TYPE_FLOAT:\n"
        "\t\tvar bytes = PackedByteArray()\n"
        "\t\tbytes.resize(8)\n"
        "\t\tbytes.encode_double(0, value)\n"
        '\t\treturn {"float_bits": bytes.decode_s64(0)}\n'
        "\tif GMRuntime.is_undefined(value):\n"
        '\t\treturn {"undefined": true}\n'
        "\treturn value\n\n\n"
        "func _ready():\n"
        f"\tvar local = [\n{block(local_cases)}\t]\n"
        "\tvar now = _encode(GMRuntime.gml_date_current_datetime())\n"
        '\tvar today = [GMRuntime.gml_date_is_today(GMRuntime.gml_date_current_datetime()), GMRuntime.gml_date_is_today(GMRuntime.gml_date_inc_day(GMRuntime.gml_date_current_datetime(), 2))]\n'
        '\tvar current = [GMRuntime.gml_builtin_global("current_year"), GMRuntime.gml_builtin_global("current_month"), GMRuntime.gml_builtin_global("current_day"), GMRuntime.gml_builtin_global("current_weekday"), GMRuntime.gml_builtin_global("current_hour")]\n'
        "\tGMRuntime.gml_date_set_timezone(1)\n"
        f"\tvar utc = [\n{block(utc_cases)}\t]\n"
        '\tvar current_utc = [GMRuntime.gml_builtin_global("current_year"), GMRuntime.gml_builtin_global("current_month"), GMRuntime.gml_builtin_global("current_day"), GMRuntime.gml_builtin_global("current_weekday"), GMRuntime.gml_builtin_global("current_hour")]\n'
        f'\tprint({json.dumps(_RESULT_PREFIX)} + JSON.stringify({{"local": local, "utc": utc, "now": now, "today": today, "current": current, "current_utc": current_utc}}))\n'
        "\tget_tree().quit(0)\n"
    )


def _decode(value: object) -> object:
    if isinstance(value, dict):
        encoded = cast(dict[str, object], value)
        if "undefined" in encoded:
            return None
        bits = int(cast(int, encoded["float_bits"])) % 2**64
        return float(memoryview(bits.to_bytes(8, "little")).cast("d")[0])
    return value


def _same(actual: object, expected: object) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, str) or isinstance(actual, str):
        return actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if math.isnan(expected):
            return math.isnan(actual)
        return float(actual) == float(expected)
    return actual == expected


def _current_fields(zone: tzinfo) -> list[int]:
    moment = datetime.now(zone)
    return [moment.year, moment.month, moment.day, (moment.weekday() + 1) % 7, moment.hour]


class TestDatesGodot(unittest.TestCase):
    def _run(self, tz_setting: str, zone: tzinfo) -> None:
        godot_binary = find_smoke_godot_binary()
        if godot_binary is None:
            self.skipTest("Godot binary not available")
        now = float(math.floor(time.time() * 1000))
        local_cases = _cases(_Runner(_JSDate(zone, False), now))
        utc_cases = _cases(_Runner(_JSDate(zone, True), now))
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            write_fixture_text(
                project_dir / "project.godot",
                '[application]\nconfig/name="Dates"\nrun/main_scene="res://probe.tscn"\n',
            )
            write_gml_runtime(str(project_dir))
            write_fixture_text(project_dir / "probe.gd", _probe_script(local_cases, utc_cases))
            write_fixture_text(
                project_dir / "probe.tscn",
                '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://probe.gd" id="1"]\n\n'
                '[node name="Probe" type="Node"]\nscript = ExtResource("1")\n',
            )
            result = subprocess.run(
                [godot_binary, "--headless", "--path", str(project_dir), "--quit-after", "60"],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                env=dict(os.environ, HOME=str(project_dir), TZ=tz_setting),
            )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-3000:])
        self.assertNotIn("SCRIPT ERROR", output)
        self.assertNotIn("GML runtime error", output)
        lines = [line for line in output.splitlines() if line.startswith(_RESULT_PREFIX)]
        self.assertEqual(len(lines), 1, output[-3000:])
        results = json.loads(lines[0].removeprefix(_RESULT_PREFIX))
        for mode, cases in (("local", local_cases), ("utc", utc_cases)):
            actual_values = [_decode(value) for value in results[mode]]
            self.assertEqual(len(actual_values), len(cases))
            for (gml, expected), actual in zip(cases, actual_values, strict=True):
                with self.subTest(tz=tz_setting, mode=mode, gml=gml):
                    self.assertTrue(_same(actual, expected), f"{actual!r} != {expected!r}")
        now_value = _decode(results["now"])
        assert isinstance(now_value, float)
        self.assertLess(abs(now_value - (time.time() / 86400.0 + _DAYS_SINCE_1900)), 30 / 86400.0)
        self.assertEqual(results["today"], [True, False])
        self.assertEqual(results["current"], _current_fields(zone))
        self.assertEqual(results["current_utc"], _current_fields(timezone.utc))

    def test_dates_in_utc(self) -> None:
        self._run("UTC", ZoneInfo("UTC"))

    def test_dates_across_new_york_daylight_saving(self) -> None:
        self._run("America/New_York", ZoneInfo("America/New_York"))

    def test_dates_across_sydney_daylight_saving(self) -> None:
        self._run("Australia/Sydney", ZoneInfo("Australia/Sydney"))

    def test_dates_in_a_half_hour_zone(self) -> None:
        self._run("Asia/Kolkata", ZoneInfo("Asia/Kolkata"))

    def test_dates_with_a_posix_tz_rule(self) -> None:
        # Without zone data the TZ variable can hold the rules themselves; the
        # rules apply to every year.
        self._run("EST5EDT,M3.2.0,M11.1.0", _PosixRules(-5, -4, (3, 2, 0, 7200), (11, 1, 0, 7200)))

    def test_dates_with_a_southern_posix_tz_rule(self) -> None:
        self._run("AEST-10AEDT,M10.1.0,M4.1.0/3", _PosixRules(10, 11, (10, 1, 0, 7200), (4, 1, 0, 10800)))


if __name__ == "__main__":
    unittest.main()
