"""
Контроль розпізнаної таблиці перед завантаженням у 1С: суми, кількість позицій, дробові кількості,
нечислові значення. Рівні: ok / warn / error.
"""
from decimal import Decimal, InvalidOperation

import converter
import profiles

MAX_LISTED = 8


def to_decimal(value):
    s = str(value or "").strip()
    if not s:
        return None
    n = converter.normalize_number(s).replace(" ", "").replace(" ", "")
    try:
        return Decimal(n)
    except InvalidOperation:
        return None


def _qty_decimal(value):
    qty, _ = profiles.split_quantity(value)
    return to_decimal(qty)


def _fmt(d):
    return format(d.quantize(Decimal("0.01")), "f").replace(".", ",")


def _rows_list(numbers):
    shown = ", ".join(str(n) for n in numbers[:MAX_LISTED])
    return shown + (f" і ще {len(numbers) - MAX_LISTED}" if len(numbers) > MAX_LISTED else "")


def run_checks(prepared, mapping, info=None):
    """prepared: рядки таблиці (заголовок + дані); mapping: {поле: заголовок};
    info: {поле: значення} реквізитів документа. Повертає [(рівень, текст)]."""
    info = info or {}
    results = []
    items, totals = profiles.extract_items(prepared, mapping)

    for field, label in (("Наименование", "назва"), ("Количество", "кількість"), ("Сумма", "сума")):
        if not mapping.get(field):
            results.append(("error", f"Не знайдено колонку «{label}» - перевірте підбір колонок."))
    if not items:
        results.append(("error", "У таблиці немає рядків з товарами."))
        return results

    results.append(("ok", f"Позицій у таблиці: {len(items)}."))

    declared = info.get("Кількість найменувань")
    if declared and declared.strip().isdigit():
        if int(declared) == len(items):
            results.append(("ok", f"Кількість позицій збігається з документом ({declared})."))
        else:
            results.append(("error", f"Позицій {len(items)}, а в документі «Всього найменувань» {declared}."))

    bad_numbers, bad_rows, fractional, zero_price, empty_names = [], [], [], [], []
    total_sum = Decimal(0)
    have_sum = False
    for n, item in enumerate(items, 1):
        qty, price, total = _qty_decimal(item.get("Количество")), to_decimal(item.get("Цена")), to_decimal(item.get("Сумма"))
        for label, raw, parsed in (
            ("кількість", item.get("Количество"), qty),
            ("ціна", item.get("Цена"), price),
            ("сума", item.get("Сумма"), total),
        ):
            if str(raw or "").strip() and parsed is None:
                bad_numbers.append(f"{n} ({label}: «{raw}»)")
        if not str(item.get("Наименование", "")).strip():
            empty_names.append(n)
        if qty is not None and qty != qty.to_integral_value():
            fractional.append(n)
        if total is not None:
            total_sum += total
            have_sum = True
            if qty is not None and price is not None:
                diff = abs(qty * price - total)
                if diff > Decimal("0.02") and diff > abs(total) * Decimal("0.005"):
                    bad_rows.append(f"{n} ({_fmt(qty * price)} замість {_fmt(total)})")
        if price is not None and price == 0:
            zero_price.append(n)

    if bad_numbers:
        results.append(("error", "Не розпізнано число: рядок " + _rows_list(bad_numbers) + "."))
    if empty_names:
        results.append(("error", "Порожня назва товару: рядок " + _rows_list(empty_names) + "."))
    if bad_rows:
        results.append(("warn", "Кількість × ціна ≠ сума: рядок " + _rows_list(bad_rows) + "."))
    elif have_sum and not bad_numbers:
        results.append(("ok", "У кожному рядку кількість × ціна = сума."))
    if fractional:
        results.append((
            "warn",
            "Дробова кількість у рядках " + _rows_list(fractional) + ": обробки 1С відкидають дробову частину "
            "(ТолькоЦифры / УбратьБуквы), а ціна рахується як Сума / Кількість.",
        ))
    if zero_price:
        results.append(("warn", "Нульова ціна: рядок " + _rows_list(zero_price) + "."))

    if have_sum:
        results.append(("ok", f"Сума по рядках: {_fmt(total_sum)}."))
        declared_total = to_decimal(info.get("Разом"))
        if declared_total is None and totals:
            declared_total = to_decimal(totals[-1].get("Сумма"))
        if declared_total is not None:
            if abs(declared_total - total_sum) <= Decimal("0.01"):
                results.append(("ok", f"Сума збігається з «Разом» документа ({_fmt(declared_total)})."))
            else:
                results.append((
                    "error",
                    f"Сума по рядках {_fmt(total_sum)} не збігається з «Разом» {_fmt(declared_total)} "
                    f"(різниця {_fmt(abs(declared_total - total_sum))}) - можлива помилка розпізнавання.",
                ))
        else:
            results.append(("warn", "У документі не знайдено «Разом» - сума не звірена."))
    return results


def summary(results):
    errors = sum(1 for level, _ in results if level == "error")
    warns = sum(1 for level, _ in results if level == "warn")
    if errors:
        return f"✗ {errors}"
    if warns:
        return f"⚠ {warns}"
    return "✓"
