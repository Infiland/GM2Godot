

# GameMaker's date functions as the HTML5 runner computes them
# (functions/Function_Date.js). A datetime is days since 1899-12-30: a
# JavaScript time value (milliseconds since 1970-01-01 UTC) / 86400000 +
# 25569. The runner reads and sets its fields with JavaScript's Date in local
# time, or in UTC after date_set_timezone(timezone_utc).

const GML_DATE_DAYS_SINCE_1900 = 25569.0
const GML_DATE_MS_PER_DAY = 86400000.0
const GML_TIMEZONE_LOCAL = 0
const GML_TIMEZONE_UTC = 1

static var _gml_date_local_time = true
# The local time zone's rules, read once (see _gml_time_zone).
static var _gml_time_zone_rules = null


static func gml_date_set_timezone(timezone):
	_gml_date_local_time = _gml_colour_int32(timezone) == GML_TIMEZONE_LOCAL
	return gml_undefined()


static func gml_date_get_timezone():
	return GML_TIMEZONE_LOCAL if _gml_date_local_time else GML_TIMEZONE_UTC


static func gml_date_current_datetime():
	var now = _gml_date_now()
	return (now - fposmod(now, 1000.0)) / GML_DATE_MS_PER_DAY + GML_DATE_DAYS_SINCE_1900


# new Date(); setFullYear(year, month - 1, day); setHours(hour, minute,
# second, 10), in local time or UTC: the runner's datetimes carry 10 ms.
static func gml_date_create_datetime(year, month, day, hour, minute, second):
	var date_day = _gml_date_make_day(_gml_colour_int32(year), _gml_colour_int32(month) - 1, _gml_colour_int32(day))
	var clock = _gml_date_make_time(_gml_colour_int32(hour), _gml_colour_int32(minute), _gml_colour_int32(second), 10)
	var now = _gml_date_now()
	var time = NAN
	if _gml_date_local_time:
		var local_now = now + _gml_date_offset_ms(now)
		time = _gml_date_time_clip(_gml_date_utc_from_local(_gml_date_make_date(date_day, fposmod(local_now, GML_DATE_MS_PER_DAY))))
		if not is_nan(time):
			var local = time + _gml_date_offset_ms(time)
			time = _gml_date_time_clip(_gml_date_utc_from_local(_gml_date_make_date(floor(local / GML_DATE_MS_PER_DAY), clock)))
	else:
		time = _gml_date_time_clip(_gml_date_make_date(date_day, fposmod(now, GML_DATE_MS_PER_DAY)))
		if not is_nan(time):
			time = _gml_date_time_clip(_gml_date_make_date(floor(time / GML_DATE_MS_PER_DAY), clock))
	return _gml_date_to_datetime(time)


static func gml_date_valid_datetime(year, month, day, hour, minute, second):
	var y = _gml_colour_int32(year)
	var m = _gml_colour_int32(month)
	var d = _gml_colour_int32(day)
	if y < 1970 or m < 1 or m > 12 or d < 1 or d > 31:
		return 0
	var h = _gml_colour_int32(hour)
	var mi = _gml_colour_int32(minute)
	var s = _gml_colour_int32(second)
	if h < 0 or h > 23 or mi < 0 or mi > 59 or s < 0 or s > 59:
		return 0
	if d > _gml_date_month_lengths(y)[m - 1]:
		return 0
	return 1


static func gml_date_get_year(datetime):
	return _gml_date_field(datetime, "year")


static func gml_date_get_month(datetime):
	return _gml_date_field(datetime, "month") + 1


static func gml_date_get_day(datetime):
	return _gml_date_field(datetime, "day")


static func gml_date_get_weekday(datetime):
	return _gml_date_field(datetime, "weekday")


static func gml_date_get_hour(datetime):
	return _gml_date_field(datetime, "hour")


static func gml_date_get_minute(datetime):
	return _gml_date_field(datetime, "minute")


static func gml_date_get_second(datetime):
	return _gml_date_field(datetime, "second")


static func gml_date_get_week(datetime):
	return floor(gml_date_get_day_of_year(datetime) / 7.0)


static func gml_date_get_day_of_year(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return NAN
	var day = 0
	var lengths = _gml_date_month_lengths(fields["year"])
	for index in range(fields["month"]):
		day += lengths[index]
	return day + fields["day"]


static func gml_date_get_hour_of_year(datetime):
	return (gml_date_get_day_of_year(datetime) - 1) * 24 + _gml_date_field(datetime, "hour")


static func gml_date_get_minute_of_year(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return NAN
	return (gml_date_get_day_of_year(datetime) - 1) * 24 * 60 + fields["hour"] * 60 + fields["minute"]


static func gml_date_get_second_of_year(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return NAN
	return (gml_date_get_day_of_year(datetime) - 1) * 24 * 60 * 60 + fields["hour"] * 3600 + fields["minute"] * 60 + fields["second"]


# date_inc_*: the JavaScript UTC setters on the date's UTC fields.
static func gml_date_inc_year(datetime, amount):
	return _gml_date_inc_day_fields(datetime, _gml_colour_int32(amount), 0, 0)


static func gml_date_inc_month(datetime, amount):
	return _gml_date_inc_day_fields(datetime, 0, _gml_colour_int32(amount), 0)


static func gml_date_inc_week(datetime, amount):
	return _gml_date_inc_day_fields(datetime, 0, 0, _gml_colour_int32(amount) * 7)


static func gml_date_inc_day(datetime, amount):
	return _gml_date_inc_day_fields(datetime, 0, 0, _gml_colour_int32(amount))


static func gml_date_inc_hour(datetime, amount):
	return _gml_date_inc_clock_fields(datetime, _gml_colour_int32(amount), 0, 0)


static func gml_date_inc_minute(datetime, amount):
	return _gml_date_inc_clock_fields(datetime, 0, _gml_colour_int32(amount), 0)


static func gml_date_inc_second(datetime, amount):
	return _gml_date_inc_clock_fields(datetime, 0, 0, _gml_colour_int32(amount))


# date_*_span: |floor(milliseconds between / 1000)| in the unit, a fraction
# for an incomplete one (years of 365.25 days, months of 30.4375 days).
static func gml_date_year_span(datetime1, datetime2):
	return absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0) / 60.0 / 60.0 / 24.0 / 365.25)


static func gml_date_month_span(datetime1, datetime2):
	return absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0) / 60.0 / 60.0 / 24.0 / 30.4375)


static func gml_date_week_span(datetime1, datetime2):
	return absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0) / 60.0 / 60.0 / 24.0 / 7.0)


static func gml_date_day_span(datetime1, datetime2):
	return absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0) / 60.0 / 60.0 / 24.0)


static func gml_date_hour_span(datetime1, datetime2):
	return absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0) / 60.0 / 60.0)


static func gml_date_minute_span(datetime1, datetime2):
	return absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0) / 60.0)


static func gml_date_second_span(datetime1, datetime2):
	return _gml_colour_int32(absf(floor(_gml_date_difference(datetime1, datetime2) / 1000.0)))


static func gml_date_compare_datetime(datetime1, datetime2):
	var first = _gml_colour_real(datetime1)
	var second = _gml_colour_real(datetime2)
	if first < second:
		return -1
	if first > second:
		return 1
	return 0


# The runner compares the local date and time here whatever the time zone.
static func gml_date_compare_date(datetime1, datetime2):
	var first = _gml_date_fields_of(datetime1, true)
	var second = _gml_date_fields_of(datetime2, true)
	var first_value = NAN if first == null else float(first["year"] * 366 + first["month"] * 31 + first["day"])
	var second_value = NAN if second == null else float(second["year"] * 366 + second["month"] * 31 + second["day"])
	return _gml_date_compare_values(first_value, second_value)


static func gml_date_compare_time(datetime1, datetime2):
	var first = _gml_date_fields_of(datetime1, true)
	var second = _gml_date_fields_of(datetime2, true)
	var first_value = NAN if first == null else float(first["hour"] * 3600 + first["minute"] * 60 + first["second"])
	var second_value = NAN if second == null else float(second["hour"] * 3600 + second["minute"] * 60 + second["second"])
	return _gml_date_compare_values(first_value, second_value)


# The date at midnight: the runner rebuilds it with new Date(year, month,
# day) (local time) from the fields in the current time zone, in seconds,
# and adds half a second.
static func gml_date_date_of(datetime):
	var time = _gml_date_time_clip((_gml_colour_real(datetime) - GML_DATE_DAYS_SINCE_1900) * 86400.0 * 1000.0)
	var fields = _gml_date_fields(time, _gml_date_local_time)
	var seconds = NAN
	if fields != null:
		var year = fields["year"]
		if year >= 0 and year <= 99:
			year += 1900
		var midnight = _gml_date_time_clip(_gml_date_utc_from_local(_gml_date_make_date(_gml_date_make_day(year, fields["month"], fields["day"]), 0.0)))
		seconds = midnight / 1000.0
		if not _gml_date_local_time and not is_nan(midnight):
			var offset_minutes = (midnight - (midnight + _gml_date_offset_ms(midnight))) / 60000.0
			seconds -= offset_minutes * 60.0
	return ((seconds + 0.5) / 86400.0) + GML_DATE_DAYS_SINCE_1900


static func gml_date_time_of(datetime):
	var value = _gml_colour_real(datetime)
	return value - _gml_colour_int32(value)


static func gml_date_datetime_string(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return "NaN/NaN/NaN NaN:NaN:NaN"
	return _gml_date_text(fields) + " " + _gml_date_clock_text(fields)


static func gml_date_date_string(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return "NaN/NaN/NaN"
	return _gml_date_text(fields)


static func gml_date_time_string(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return "invalid time"
	return _gml_date_clock_text(fields)


static func gml_date_days_in_month(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return gml_undefined()
	return _gml_date_month_lengths(fields["year"])[fields["month"]]


static func gml_date_days_in_year(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields != null and _gml_date_is_leap_year(fields["year"]):
		return 366
	return 365


static func gml_date_leap_year(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	return fields != null and _gml_date_is_leap_year(fields["year"])


static func gml_date_is_today(datetime):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	var today = _gml_date_fields(_gml_date_now(), _gml_date_local_time)
	return fields != null and fields["year"] == today["year"] and fields["month"] == today["month"] and fields["day"] == today["day"]


# current_year, current_month, ... in the current time zone.
static func gml_date_current_field(field):
	var fields = _gml_date_fields(_gml_date_now(), _gml_date_local_time)
	if field == "month":
		return fields["month"] + 1
	return fields[field]


static func _gml_date_now():
	return floor(Time.get_unix_time_from_system() * 1000.0)


static func _gml_date_to_datetime(time):
	return time / GML_DATE_MS_PER_DAY + GML_DATE_DAYS_SINCE_1900


# FromGMDateTime: a value before 1970 is taken as days since 1970.
static func _gml_date_time_of_datetime(datetime):
	var value = _gml_colour_real(datetime)
	if value < GML_DATE_DAYS_SINCE_1900:
		return _gml_date_time_clip(value * GML_DATE_MS_PER_DAY)
	return _gml_date_time_clip((value - GML_DATE_DAYS_SINCE_1900) * GML_DATE_MS_PER_DAY)


static func _gml_date_fields_of(datetime, local):
	return _gml_date_fields(_gml_date_time_of_datetime(datetime), local)


static func _gml_date_field(datetime, field):
	var fields = _gml_date_fields_of(datetime, _gml_date_local_time)
	if fields == null:
		return NAN
	return fields[field]


static func _gml_date_difference(datetime1, datetime2):
	return _gml_date_time_of_datetime(datetime2) - _gml_date_time_of_datetime(datetime1)


static func _gml_date_compare_values(first, second):
	if first == second:
		return 0.0
	return 1.0 if first > second else -1.0


static func _gml_date_inc_day_fields(datetime, years, months, days):
	var time = _gml_date_time_of_datetime(datetime)
	var fields = _gml_date_fields(time, false)
	if fields == null:
		return NAN
	var date_day = _gml_date_make_day(fields["year"] + years, fields["month"] + months, fields["day"] + days)
	return _gml_date_to_datetime(_gml_date_time_clip(_gml_date_make_date(date_day, fposmod(time, GML_DATE_MS_PER_DAY))))


static func _gml_date_inc_clock_fields(datetime, hours, minutes, seconds):
	var time = _gml_date_time_of_datetime(datetime)
	var fields = _gml_date_fields(time, false)
	if fields == null:
		return NAN
	var clock = _gml_date_make_time(fields["hour"] + hours, fields["minute"] + minutes, fields["second"] + seconds, fields["millisecond"])
	return _gml_date_to_datetime(_gml_date_time_clip(_gml_date_make_date(floor(time / GML_DATE_MS_PER_DAY), clock)))


static func _gml_date_pad2(value):
	return ("0" if value < 10 else "") + str(value)


static func _gml_date_text(fields):
	return _gml_date_pad2(fields["day"]) + "/" + _gml_date_pad2(fields["month"] + 1) + "/" + str(fields["year"])


static func _gml_date_clock_text(fields):
	return _gml_date_pad2(fields["hour"]) + ":" + _gml_date_pad2(fields["minute"]) + ":" + _gml_date_pad2(fields["second"])


static func _gml_date_is_leap_year(year):
	return year % 400 == 0 or (year % 100 != 0 and year % 4 == 0)


static func _gml_date_month_lengths(year):
	return [31, 29 if _gml_date_is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


# JavaScript TimeClip: NaN for a time that is not finite or is beyond
# 8.64e15 ms, else the time truncated toward zero.
static func _gml_date_time_clip(time):
	if is_nan(time) or is_inf(time) or absf(time) > 8.64e15:
		return NAN
	return float(int(time))


# JavaScript MakeDay (year, month from 0, date from 1; months overflow into
# years and dates into months).
static func _gml_date_make_day(year, month, date):
	if is_nan(float(year)) or is_nan(float(month)) or is_nan(float(date)):
		return NAN
	var whole_year = int(year) + int(floor(float(month) / 12.0))
	var whole_month = posmod(int(month), 12)
	return float(_gml_date_days_from_civil(whole_year, whole_month + 1, 1)) + float(date) - 1.0


static func _gml_date_make_time(hour, minute, second, millisecond):
	return float(hour) * 3600000.0 + float(minute) * 60000.0 + float(second) * 1000.0 + float(millisecond)


static func _gml_date_make_date(day, time):
	var value = day * GML_DATE_MS_PER_DAY + time
	if is_nan(value) or is_inf(value):
		return NAN
	return value


# Days since 1970-01-01 of a proleptic Gregorian date (H. Hinnant's
# days_from_civil).
static func _gml_date_days_from_civil(year, month, day):
	var y = year - (1 if month <= 2 else 0)
	var era = floori(y / 400.0)
	var year_of_era = y - era * 400
	var day_of_year = floori((153 * (month - 3 if month > 2 else month + 9) + 2) / 5.0) + day - 1
	var day_of_era = year_of_era * 365 + floori(year_of_era / 4.0) - floori(year_of_era / 100.0) + day_of_year
	return era * 146097 + day_of_era - 719468


# The year, month (from 0), day, weekday, hour, minute, second and
# millisecond of a time value, in local time or UTC; null for NaN.
static func _gml_date_fields(time, local):
	if is_nan(time):
		return null
	var moment = time + (_gml_date_offset_ms(time) if local else 0.0)
	var day_number = floori(moment / GML_DATE_MS_PER_DAY)
	var in_day = int(moment - float(day_number) * GML_DATE_MS_PER_DAY)
	var z = day_number + 719468
	var era = floori(z / 146097.0)
	var day_of_era = z - era * 146097
	var year_of_era = floori((day_of_era - floori(day_of_era / 1460.0) + floori(day_of_era / 36524.0) - floori(day_of_era / 146096.0)) / 365.0)
	var day_of_year = day_of_era - (365 * year_of_era + floori(year_of_era / 4.0) - floori(year_of_era / 100.0))
	var shifted_month = floori((5 * day_of_year + 2) / 153.0)
	var month = shifted_month + 3 if shifted_month < 10 else shifted_month - 9
	return {
		"year": year_of_era + era * 400 + (1 if month <= 2 else 0),
		"month": month - 1,
		"day": day_of_year - floori((153 * shifted_month + 2) / 5.0) + 1,
		"weekday": posmod(day_number + 4, 7),
		"hour": floori(in_day / 3600000.0),
		"minute": floori(in_day / 60000.0) % 60,
		"second": floori(in_day / 1000.0) % 60,
		"millisecond": in_day % 1000,
	}


# JavaScript UTC(t) for a local time value: an ambiguous local time is the
# earlier instant, and one skipped by a transition uses the offset before it.
static func _gml_date_utc_from_local(local_time):
	if is_nan(local_time):
		return NAN
	var before = _gml_date_offset_ms(local_time - GML_DATE_MS_PER_DAY)
	var after = _gml_date_offset_ms(local_time + GML_DATE_MS_PER_DAY)
	var earlier = local_time - before
	var later = local_time - after
	var earlier_fits = _gml_date_offset_ms(earlier) == before
	var later_fits = _gml_date_offset_ms(later) == after
	if earlier_fits and later_fits:
		return minf(earlier, later)
	if later_fits and not earlier_fits:
		return later
	return earlier


# The local time zone's offset from UTC, in milliseconds, at a UTC time.
static func _gml_date_offset_ms(time):
	return float(_gml_time_zone_offset(floori(time / 1000.0))) * 1000.0


# Seconds east of UTC at a UTC time in seconds, from the zone's transitions
# and, after the last one, its POSIX TZ rule.
static func _gml_time_zone_offset(utc_seconds):
	var zone = _gml_time_zone()
	var times: PackedInt64Array = zone["times"]
	if times.is_empty() or utc_seconds >= times[times.size() - 1]:
		if zone["rule"] != null:
			return _gml_time_zone_rule_offset(zone["rule"], utc_seconds)
		if times.is_empty():
			return zone["initial"]
	if utc_seconds < times[0]:
		return zone["initial"]
	return zone["offsets"][times.bsearch(utc_seconds, false) - 1]


# The local time zone as the C library finds it: TZ (a zone name, a file or
# a POSIX TZ string; set but empty means UTC), else /etc/localtime. Without
# zone data (for example on Windows) the system's current offset is used for
# every date.
static func _gml_time_zone():
	if _gml_time_zone_rules != null:
		return _gml_time_zone_rules
	var zone = {"times": PackedInt64Array(), "offsets": PackedInt32Array(), "initial": 0, "rule": null}
	var name = ""
	var path = "/etc/localtime"
	if OS.has_environment("TZ"):
		name = OS.get_environment("TZ").trim_prefix(":")
		var directory = OS.get_environment("TZDIR") if OS.has_environment("TZDIR") else "/usr/share/zoneinfo"
		path = name if name.begins_with("/") else directory.path_join(name)
	var loaded = null
	if (OS.has_environment("TZ") == false or not name.is_empty()) and not path.contains("..") and FileAccess.file_exists(path):
		loaded = _gml_time_zone_parse_tzif(FileAccess.get_file_as_bytes(path))
	if loaded != null:
		zone = loaded
	elif OS.has_environment("TZ"):
		zone["rule"] = _gml_time_zone_parse_posix(name)
	else:
		zone["initial"] = int(Time.get_time_zone_from_system().get("bias", 0)) * 60
	_gml_time_zone_rules = zone
	return zone


static func _gml_time_zone_big_endian(data, offset, size):
	var value = 0
	for index in range(size):
		value = (value << 8) | data[offset + index]
	if size == 4 and value >= 0x80000000:
		value -= 0x100000000
	return value


# A TZif file (RFC 8536): its transitions and footer rule, or null.
static func _gml_time_zone_parse_tzif(data):
	if data.size() < 44 or data.slice(0, 4).get_string_from_ascii() != "TZif":
		return null
	var counts = []
	for index in range(6):
		counts.append(_gml_time_zone_big_endian(data, 20 + index * 4, 4))
	var offset = 44
	var time_size = 4
	if data[4] >= 0x32:
		# Version 2 and later repeat the data with 64-bit times.
		offset += counts[3] * 5 + counts[4] * 6 + counts[5] + counts[2] * 8 + counts[1] + counts[0]
		if data.size() < offset + 44 or data.slice(offset, offset + 4).get_string_from_ascii() != "TZif":
			return null
		counts = []
		for index in range(6):
			counts.append(_gml_time_zone_big_endian(data, offset + 20 + index * 4, 4))
		offset += 44
		time_size = 8
	var time_count = counts[3]
	var type_count = counts[4]
	var end = offset + time_count * (time_size + 1) + type_count * 6 + counts[5] + counts[2] * (time_size + 4) + counts[1] + counts[0]
	if type_count < 1 or data.size() < end:
		return null
	var type_offsets = []
	var types_start = offset + time_count * (time_size + 1)
	for index in range(type_count):
		type_offsets.append(_gml_time_zone_big_endian(data, types_start + index * 6, 4))
	var times = PackedInt64Array()
	var offsets = PackedInt32Array()
	for index in range(time_count):
		times.append(_gml_time_zone_big_endian(data, offset + index * time_size, time_size))
		offsets.append(type_offsets[mini(data[offset + time_count * time_size + index], type_count - 1)])
	var rule = null
	if time_size == 8 and end < data.size() and data[end] == 0x0A:
		var footer_end = data.find(0x0A, end + 1)
		if footer_end > end + 1:
			rule = _gml_time_zone_parse_posix(data.slice(end + 1, footer_end).get_string_from_ascii())
	return {"times": times, "offsets": offsets, "initial": type_offsets[0], "rule": rule}


# A POSIX TZ string such as "CET-1CEST,M3.5.0,M10.5.0/3": offsets in seconds
# east of UTC and the start and end of daylight time; null if malformed.
static func _gml_time_zone_parse_posix(text):
	var reader = {"text": text, "at": 0}
	if _gml_time_zone_read_name(reader) == null:
		return null
	var standard = _gml_time_zone_read_seconds(reader)
	if standard == null:
		return null
	var rule = {"standard": -standard, "daylight": null}
	if reader["at"] >= text.length():
		return rule
	if _gml_time_zone_read_name(reader) == null:
		return null
	var daylight = standard - 3600
	if reader["at"] < text.length() and text[reader["at"]] != ",":
		daylight = _gml_time_zone_read_seconds(reader)
		if daylight == null:
			return null
	rule["daylight"] = -daylight
	# Without dates, the US rules the C library assumes.
	rule["start"] = {"kind": "M", "month": 3, "week": 2, "weekday": 0, "time": 7200}
	rule["end"] = {"kind": "M", "month": 11, "week": 1, "weekday": 0, "time": 7200}
	if reader["at"] < text.length():
		if text[reader["at"]] != ",":
			return null
		reader["at"] += 1
		rule["start"] = _gml_time_zone_read_date(reader)
		if rule["start"] == null or reader["at"] >= text.length() or text[reader["at"]] != ",":
			return null
		reader["at"] += 1
		rule["end"] = _gml_time_zone_read_date(reader)
		if rule["end"] == null:
			return null
	return rule


static func _gml_time_zone_read_name(reader):
	var text: String = reader["text"]
	var start = reader["at"]
	if start < text.length() and text[start] == "<":
		var close = text.find(">", start)
		if close < 0:
			return null
		reader["at"] = close + 1
		return text.substr(start + 1, close - start - 1)
	var at = start
	while at < text.length() and ((text[at] >= "A" and text[at] <= "Z") or (text[at] >= "a" and text[at] <= "z")):
		at += 1
	if at - start < 3:
		return null
	reader["at"] = at
	return text.substr(start, at - start)


# [+|-]hh[:mm[:ss]] as seconds.
static func _gml_time_zone_read_seconds(reader):
	var text: String = reader["text"]
	var sign = 1
	if reader["at"] < text.length() and (text[reader["at"]] == "+" or text[reader["at"]] == "-"):
		sign = -1 if text[reader["at"]] == "-" else 1
		reader["at"] += 1
	var total = 0
	for part in range(3):
		if part > 0:
			if reader["at"] >= text.length() or text[reader["at"]] != ":":
				break
			reader["at"] += 1
		var start = reader["at"]
		while reader["at"] < text.length() and text[reader["at"]] >= "0" and text[reader["at"]] <= "9":
			reader["at"] += 1
		if reader["at"] == start:
			return null
		total += int(text.substr(start, reader["at"] - start)) * [3600, 60, 1][part]
	return sign * total


# Jn, n or Mm.w.d, then an optional /time (02:00 by default).
static func _gml_time_zone_read_date(reader):
	var text: String = reader["text"]
	var date = {"kind": "N", "time": 7200}
	var numbers = []
	if reader["at"] < text.length() and (text[reader["at"]] == "J" or text[reader["at"]] == "M"):
		date["kind"] = text[reader["at"]]
		reader["at"] += 1
	for part in range(3 if date["kind"] == "M" else 1):
		if part > 0:
			if reader["at"] >= text.length() or text[reader["at"]] != ".":
				return null
			reader["at"] += 1
		var start = reader["at"]
		while reader["at"] < text.length() and text[reader["at"]] >= "0" and text[reader["at"]] <= "9":
			reader["at"] += 1
		if reader["at"] == start:
			return null
		numbers.append(int(text.substr(start, reader["at"] - start)))
	if date["kind"] == "M":
		date["month"] = numbers[0]
		date["week"] = numbers[1]
		date["weekday"] = numbers[2]
	else:
		date["day"] = numbers[0]
	if reader["at"] < text.length() and text[reader["at"]] == "/":
		reader["at"] += 1
		var time = _gml_time_zone_read_seconds(reader)
		if time == null:
			return null
		date["time"] = time
	return date


static func _gml_time_zone_rule_offset(rule, utc_seconds):
	if rule["daylight"] == null:
		return rule["standard"]
	var year = _gml_date_fields(float(utc_seconds + rule["standard"]) * 1000.0, false)["year"]
	var start = _gml_time_zone_transition(rule["start"], year) - rule["standard"]
	var end = _gml_time_zone_transition(rule["end"], year) - rule["daylight"]
	var in_daylight = utc_seconds >= start and utc_seconds < end
	if start > end:
		in_daylight = not (utc_seconds >= end and utc_seconds < start)
	return rule["daylight"] if in_daylight else rule["standard"]


# The local seconds since 1970 (as if UTC) at which a rule date takes effect.
static func _gml_time_zone_transition(date, year):
	var first_day = _gml_date_days_from_civil(year, 1, 1)
	var day = first_day
	if date["kind"] == "J":
		day += date["day"] - 1
		if _gml_date_is_leap_year(year) and date["day"] >= 60:
			day += 1
	elif date["kind"] == "N":
		day += date["day"]
	else:
		var month_start = _gml_date_days_from_civil(year, date["month"], 1)
		var month_day = 1 + posmod(date["weekday"] - posmod(month_start + 4, 7), 7) + (date["week"] - 1) * 7
		var length = _gml_date_month_lengths(year)[date["month"] - 1]
		while month_day > length:
			month_day -= 7
		day = month_start + month_day - 1
	return day * 86400 + date["time"]
