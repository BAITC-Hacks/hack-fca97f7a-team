"""Pure numeric tools over a server-stored hourly forecast.

All periods are UTC half-open intervals. The selected period is conversation
state, never a substitute for validating the stored forecast hours.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_FIELDS = ("power_norm", "wind_speed_ms", "temperature_c")
_HOUR = timedelta(hours=1)


def _schema(name: str, description: str, properties: dict) -> dict:
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(properties), "additionalProperties": False}}


def _string(description: str, nullable: bool = False) -> dict:
    return {"type": ["string", "null"] if nullable else "string", "description": description}


TOOL_SCHEMAS = [
    _schema("best_hours", "Найти лучшие или худшие N часов по прогнозной нормализованной мощности. При contiguous=true ищет непрерывное окно с лучшей или худшей средней мощностью.",
            {"count": {"type": "integer", "description": "Число часов от 1 до длины прогноза"},
             "contiguous": {"type": "boolean", "description": "Нужен ли непрерывный период"},
             "order": {"type": "string", "enum": ["best", "worst"], "description": "Лучшие или худшие часы"}}),
    _schema("period_details", "Показать ветер, температуру и мощность по каждому часу периода. null использует последний выбранный период.",
            {"start": _string("Начало периода UTC ISO 8601 или null", True),
             "end": _string("Конец периода UTC ISO 8601, не включительно, или null", True)}),
    _schema("average_power", "Вычислить среднюю нормализованную мощность за непрерывный период.",
            {"start": _string("Начало UTC ISO 8601 или null для выбранного периода", True),
             "end": _string("Конец UTC ISO 8601, не включительно, или null", True)}),
    _schema("compare_periods", "Сравнить два непрерывных периода по средней мощности, ветру и температуре. null для второго периода означает сразу следующий период той же длительности.",
            {"start": _string("Начало первого UTC периода или null для выбранного", True),
             "end": _string("Конец первого UTC периода или null для выбранного", True),
             "comparison_start": _string("Начало второго UTC периода или null для следующего", True),
             "comparison_end": _string("Конец второго UTC периода или null для следующего", True)}),
    _schema("power_changes", "Найти резкие изменения нормализованной мощности между соседними часами.",
            {"threshold": {"type": "number", "description": "Минимальный абсолютный скачок нормализованной мощности от 0 до 1"},
             "direction": {"type": "string", "enum": ["up", "down", "both"], "description": "Рост, спад или оба"}}),
]


def _stamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Время периода должно быть строкой UTC ISO 8601.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Время периода должно быть строкой UTC ISO 8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("Границы периода должны быть целыми часами в UTC.")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _number(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _zone(result: dict) -> ZoneInfo:
    try:
        return ZoneInfo(result.get("timezone", "UTC"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Часовой пояс прогноза некорректен.") from exc


def _local(value: datetime, zone: ZoneInfo) -> str:
    local = value.astimezone(zone)
    offset = local.strftime("%z")
    return f"{local:%d.%m.%Y %H:%M} UTC{offset[:3]}:{offset[3:]} ({zone.key})"


def _hours(result: dict) -> list[dict]:
    if not isinstance(result, dict) or result.get("status") != "ok" or not isinstance(result.get("hours"), list) or not result["hours"]:
        raise ValueError("Нужен сохранённый прогноз с почасовыми данными.")
    seen = set()
    rows = []
    for row in result["hours"]:
        if not isinstance(row, dict):
            raise ValueError("Почасовые данные прогноза некорректны.")
        at = _stamp(row.get("valid_at"))
        if at in seen:
            raise ValueError("В прогнозе повторяется час.")
        seen.add(at)
        values = {}
        for field in _FIELDS:
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("В прогнозе есть нечисловое или бесконечное значение.")
            values[field] = float(value)
        if not 0 <= values["power_norm"] <= 1 or values["wind_speed_ms"] < 0:
            raise ValueError("Мощность или ветер в прогнозе вне допустимого диапазона.")
        rows.append({"at": at, **values})
    rows.sort(key=lambda row: row["at"])
    return rows


def _selection(start: datetime, end: datetime) -> dict:
    return {"start": _iso(start), "end": _iso(end)}


def _period(rows: list[dict], start, end, selection) -> tuple[list[dict], dict]:
    if start is None and end is None:
        if not isinstance(selection, dict):
            raise ValueError("Сначала выберите конкретный непрерывный период прогноза.")
        start, end = selection.get("start"), selection.get("end")
    elif start is None or end is None:
        raise ValueError("Укажите обе границы периода или используйте выбранный период.")
    begin, finish = _stamp(start), _stamp(end)
    if begin >= finish:
        raise ValueError("Конец периода должен быть позже начала.")
    expected = int((finish - begin) / _HOUR)
    if expected > len(rows):
        raise ValueError("Период выходит за границы прогноза.")
    subset = [row for row in rows if begin <= row["at"] < finish]
    if len(subset) != expected or any(row["at"] != begin + i * _HOUR for i, row in enumerate(subset)):
        raise ValueError("В выбранном периоде нет полного набора последовательных часов прогноза.")
    return subset, _selection(begin, finish)


def _means(rows: list[dict]) -> dict:
    return {"mean_power_norm": sum(row["power_norm"] for row in rows) / len(rows),
            "mean_wind_speed_ms": sum(row["wind_speed_ms"] for row in rows) / len(rows),
            "mean_temperature_c": sum(row["temperature_c"] for row in rows) / len(rows)}


def _row_data(row: dict) -> dict:
    return {"valid_at": _iso(row["at"]), **{field: row[field] for field in _FIELDS}}


def _period_label(period: dict, zone: ZoneInfo) -> str:
    return f"{_local(_stamp(period['start']), zone)} — {_local(_stamp(period['end']), zone)}"


def execute_tool(result: dict, name: str, args: dict, selection: dict | None = None) -> dict:
    """Execute a named, validated numeric tool against one stored forecast."""
    if not isinstance(args, dict):
        raise ValueError("Параметры расчёта должны быть объектом.")
    rows, zone = _hours(result), _zone(result)
    names = {schema["name"]: set(schema["parameters"]["properties"]) for schema in TOOL_SCHEMAS}
    if name not in names:
        raise ValueError("Неизвестный инструмент расчёта.")
    if set(args) != names[name]:
        raise ValueError("Переданы неполные или лишние параметры расчёта.")
    if name == "best_hours":
        count, contiguous, order = args["count"], args["contiguous"], args["order"]
        if type(count) is not int or not 1 <= count <= len(rows) or type(contiguous) is not bool or order not in ("best", "worst"):
            raise ValueError("Укажите допустимое число часов, тип периода и порядок выбора.")
        if contiguous:
            windows = [rows[i:i + count] for i in range(len(rows) - count + 1)]
            windows = [group for group in windows if all(b["at"] - a["at"] == _HOUR for a, b in zip(group, group[1:]))]
            if not windows:
                raise ValueError("В прогнозе нет полного непрерывного периода такой длины.")
            group = (max if order == "best" else min)(windows, key=lambda group: _means(group)["mean_power_norm"])
            period = _selection(group[0]["at"], group[-1]["at"] + _HOUR)
            means = _means(group)
            return {"tool": name, "data": {"count": count, "contiguous": True, "order": order, **period, **means},
                    "selection": period,
                    "text": f"{'Лучшие' if order == 'best' else 'Худшие'} {count} часа подряд: {_period_label(period, zone)}. Средняя нормализованная мощность — {_number(means['mean_power_norm'])}; ветер — {_number(means['mean_wind_speed_ms'], 2)} м/с, температура — {_number(means['mean_temperature_c'], 2)} °C."}
        ranked = sorted(rows, key=lambda row: ((-1 if order == "best" else 1) * row["power_norm"], row["at"]))[:count]
        single_selection = _selection(ranked[0]["at"], ranked[0]["at"] + _HOUR) if count == 1 else None
        table = {"columns": ["Час", "Мощность [0,1]", "Ветер, м/с", "Температура, °C"],
                 "rows": [[_local(row["at"], zone), _number(row["power_norm"]), _number(row["wind_speed_ms"], 2), _number(row["temperature_c"], 2)] for row in ranked]}
        return {"tool": name, "data": {"count": count, "contiguous": False, "order": order, "hours": [_row_data(row) for row in ranked]},
                "selection": single_selection, "table": table,
                "text": (f"{'Лучший' if order == 'best' else 'Худший'} час — {_local(ranked[0]['at'], zone)}; нормализованная мощность {_number(ranked[0]['power_norm'])}."
                         if count == 1 else f"{'Лучшие' if order == 'best' else 'Худшие'} {count} отдельных часов по нормализованной мощности; они могут не идти подряд.")}
    if name in ("period_details", "average_power"):
        group, period = _period(rows, args["start"], args["end"], selection)
        means = _means(group)
        data = {**period, "count": len(group), **means}
        if name == "average_power":
            return {"tool": name, "data": data, "selection": period,
                    "text": f"Средняя нормализованная мощность за {len(group)} ч ({_period_label(period, zone)}) — {_number(means['mean_power_norm'])}."}
        data["hours"] = [_row_data(row) for row in group]
        table = {"columns": ["Час", "Ветер, м/с", "Температура, °C", "Мощность [0,1]"],
                 "rows": [[_local(row["at"], zone), _number(row["wind_speed_ms"], 2), _number(row["temperature_c"], 2), _number(row["power_norm"])] for row in group]}
        return {"tool": name, "data": data, "selection": period, "table": table,
                "text": f"За период {_period_label(period, zone)}: средний ветер — {_number(means['mean_wind_speed_ms'], 2)} м/с, температура — {_number(means['mean_temperature_c'], 2)} °C, нормализованная мощность — {_number(means['mean_power_norm'])}."}
    if name == "compare_periods":
        first, first_period = _period(rows, args["start"], args["end"], selection)
        comparison_start, comparison_end = args["comparison_start"], args["comparison_end"]
        if comparison_start is None and comparison_end is None:
            comparison_start = first_period["end"]
            comparison_end = _iso(_stamp(comparison_start) + len(first) * _HOUR)
        second, second_period = _period(rows, comparison_start, comparison_end, None)
        a, b = _means(first), _means(second)
        table = {"columns": ["Период", "Часы", "Средняя мощность [0,1]", "Средний ветер, м/с", "Средняя температура, °C"],
                 "rows": [[_period_label(p, zone), str(len(group)), _number(means["mean_power_norm"]), _number(means["mean_wind_speed_ms"], 2), _number(means["mean_temperature_c"], 2)] for p, group, means in ((first_period, first, a), (second_period, second, b))]}
        return {"tool": name, "data": {"first": {**first_period, "count": len(first), **a}, "second": {**second_period, "count": len(second), **b}, "delta_mean_power_norm": b["mean_power_norm"] - a["mean_power_norm"]},
                "selection": second_period, "table": table,
                "text": f"Первый период ({_period_label(first_period, zone)}): средняя нормализованная мощность {_number(a['mean_power_norm'])}. Второй ({_period_label(second_period, zone)}): {_number(b['mean_power_norm'])}; разница с первым {_number(b['mean_power_norm'] - a['mean_power_norm'])}."}
    threshold, direction = args["threshold"], args["direction"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1 or direction not in ("up", "down", "both"):
        raise ValueError("Укажите порог от 0 до 1 и направление изменения.")
    changes = []
    for previous, current in zip(rows, rows[1:]):
        if current["at"] - previous["at"] != _HOUR:
            continue
        delta = current["power_norm"] - previous["power_norm"]
        if delta != 0 and abs(delta) >= threshold and (direction == "both" or (direction == "up" and delta > 0) or (direction == "down" and delta < 0)):
            changes.append({"from": _iso(previous["at"]), "to": _iso(current["at"]), "delta_power_norm": delta,
                            "power_before_norm": previous["power_norm"], "power_after_norm": current["power_norm"],
                            "wind_before_ms": previous["wind_speed_ms"], "wind_after_ms": current["wind_speed_ms"],
                            "temperature_before_c": previous["temperature_c"], "temperature_after_c": current["temperature_c"]})
    table = {"columns": ["Первый час", "Следующий час", "Мощность [0,1]", "Изменение мощности [0,1]", "Ветер, м/с", "Температура, °C"],
             "rows": [[_local(_stamp(item["from"]), zone), _local(_stamp(item["to"]), zone),
                       f"{_number(item['power_before_norm'])} → {_number(item['power_after_norm'])}", _number(item["delta_power_norm"]),
                       f"{_number(item['wind_before_ms'], 2)} → {_number(item['wind_after_ms'], 2)}",
                       f"{_number(item['temperature_before_c'], 2)} → {_number(item['temperature_after_c'], 2)}"] for item in changes]}
    return {"tool": name, "data": {"threshold": float(threshold), "direction": direction, "changes": changes}, "table": table,
            "text": f"Найдено изменений мощности между соседними часами с порогом {_number(threshold)}: {len(changes)}. Сопоставление погоды и мощности не доказывает физическую причину."}


_NUMBERS = {"один": 1, "одного": 1, "два": 2, "двух": 2, "три": 3, "трех": 3, "трёх": 3,
            "четыре": 4, "четырех": 4, "четырёх": 4, "четырьмя": 4, "пять": 5, "пяти": 5,
            "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8,
            "девять": 9, "девяти": 9, "десять": 10, "десяти": 10}
_COUNT_RE = re.compile(r"(?<!\w)(\d{1,2}|" + "|".join(_NUMBERS) +
                       r")(?:[-\s]+(?:отдельн\w*|последовательн\w*|непрерывн\w*))*[-\s]*час\w*", re.I)
_ISO_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:00:00(?:Z|\+00:00)", re.I)


def _count(question: str) -> int | None:
    match = _COUNT_RE.search(question)
    if not match:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _NUMBERS[token]


def local_question(result: dict, question: str, selection: dict | None = None) -> dict | None:
    """Conservative Russian fallback for clear forecast questions; None means unsupported."""
    if not isinstance(question, str):
        return None
    q = question.strip().lower()
    if not q:
        return None
    if re.search(r"сколько.*(?:выработ|мвт|энерг)|(?:выработ|энерг).*сколько", q):
        return {"tool": "clarification", "data": {}, "text": "МВт·ч нельзя рассчитать без номинальной мощности установки в МВт. Здесь доступна только нормализованная мощность [0,1]."}
    if re.search(r"когда\s+лучше\s*[?!.]*\s*$", q):
        return {"tool": "clarification", "data": {}, "text": "Вам нужен отдельный лучший час или непрерывный период? Укажите число часов для периода."}
    count = _count(q)
    best = bool(re.search(r"лучш|максим|наибольш|высок|пик", q))
    worst = bool(re.search(r"худш|миним|наименьш|низк", q))
    if count is None and re.search(r"\b(?:час|часа|часов)\b", q) and re.search(r"\b(?:первый|один|одного)\b", q):
        count = 1
    if count is None and re.search(r"\b(?:лучший|лучшего|худший|худшего|максимум|минимум|пик)\b", q) and re.search(r"час|мощност|прогноз", q):
        count = 1
    if count is not None and best != worst and re.search(r"час|\bч\b|мощност|прогноз", q):
        contiguous = bool(re.search(r"подряд|последовательн|непрерывн|период|окн|средн", q))
        return execute_tool(result, "best_hours", {"count": count, "contiguous": contiguous, "order": "best" if best else "worst"}, selection)
    explicit_times = _ISO_UTC_RE.findall(question)
    if len(explicit_times) == 2 and re.search(r"средн.*мощност", q):
        return execute_tool(result, "average_power", {"start": explicit_times[0], "end": explicit_times[1]}, selection)
    if len(explicit_times) == 2 and re.search(r"ветер|ветра|ветру|ветром|температур|погод|мощност", q):
        return execute_tool(result, "period_details", {"start": explicit_times[0], "end": explicit_times[1]}, selection)
    if len(explicit_times) == 4 and re.search(r"сравн|сопостав", q):
        return execute_tool(result, "compare_periods", {"start": explicit_times[0], "end": explicit_times[1],
                                                        "comparison_start": explicit_times[2], "comparison_end": explicit_times[3]}, selection)
    if selection and re.search(r"сравн|сопостав", q) and re.search(r"последующ|следующ", q):
        if count is not None:
            selected_length = int((_stamp(selection["end"]) - _stamp(selection["start"])) / _HOUR)
            if count != selected_length:
                return {"tool": "clarification", "data": {}, "text": "Уточните границы второго периода: его длительность отличается от выбранного периода."}
        return execute_tool(result, "compare_periods", {"start": None, "end": None, "comparison_start": None, "comparison_end": None}, selection)
    if selection and re.search(r"ветер|ветра|ветру|ветром|температур|погод|мощност", q) and re.search(r"там|этом|за\s+этот|выбранн|период", q):
        return execute_tool(result, "period_details", {"start": None, "end": None}, selection)
    if selection and re.search(r"средн.*мощност", q):
        return execute_tool(result, "average_power", {"start": None, "end": None}, selection)
    if not selection and re.search(r"\b(?:там|этом|выбранн\w*)\b", q) and re.search(r"ветер|ветра|ветру|ветром|температур|погод|мощност", q):
        return {"tool": "clarification", "data": {}, "text": "Уточните период прогноза: сначала выберите непрерывные часы или укажите границы в UTC."}
    if re.search(r"почему.*(?:мощност.*(?:упал|сниз|пад)|(?:упал|сниз|пад).*мощност)", q):
        answer = execute_tool(result, "power_changes", {"threshold": 0.0, "direction": "down"}, selection)
        changes = answer["data"]["changes"]
        if changes:
            largest = min(changes, key=lambda change: change["delta_power_norm"])
            answer["text"] = (f"По всему прогнозу найдено {len(changes)} снижений между соседними часами. Наибольшее: "
                              f"{_local(_stamp(largest['from']), _zone(result))} → {_local(_stamp(largest['to']), _zone(result))}; "
                              f"мощность {_number(largest['power_before_norm'])} → {_number(largest['power_after_norm'])}, "
                              f"ветер {_number(largest['wind_before_ms'], 2)} → {_number(largest['wind_after_ms'], 2)} м/с, "
                              f"температура {_number(largest['temperature_before_c'], 2)} → {_number(largest['temperature_after_c'], 2)} °C. "
                              "Эти значения не доказывают физическую причину снижения.")
        else:
            answer["text"] = "Во всём прогнозе нет снижения мощности между соседними часами."
        return answer
    if re.search(r"резк|скач|падени|изменени", q) and re.search(r"мощност", q):
        direction = "down" if re.search(r"падени|снижени", q) else "up" if re.search(r"рост|увеличени", q) else "both"
        explicit_threshold = re.search(r"(?:порог\w*|более|больше|на)\s+([-+]?\d+(?:[.,]\d+)?)\b", q)
        threshold = float(explicit_threshold.group(1).replace(",", ".")) if explicit_threshold else 0.1
        return execute_tool(result, "power_changes", {"threshold": threshold, "direction": direction}, selection)
    return None
