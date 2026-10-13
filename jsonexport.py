"""
JSON для 1С: реквізити документа (шапка) і рядки товарів в одному файлі.
Обробка УпрИмпортИзExcel читає його й одразу заповнює шапку нового документа та таблицю.

Ключі російською - як імена реквізитів у 1С. Дати у форматі ISO (для ПрочитатьДатуJSON),
числа - числа JSON, текст зберігається без очищення (лапки, переноси не чіпаємо).
"""
import json
import re

import checks
import docinfo
import profiles

FORMAT_NAME = "TableConverter"
FORMAT_VERSION = 1
PROFILE = "upr"

# Поля рядка товару, які пишемо у JSON (якщо знайдені); числові - як числа
ITEM_TEXT_FIELDS = ("Код", "Артикул", "Штрихкод", "Наименование", "Комментарий", "Единица", "УКТВЭД",
                    "ХарактеристикаНаименование")
ITEM_NUMBER_FIELDS = ("Количество", "Цена", "Сумма", "Вес", "Объем", "Высота", "Длина", "Ширина", "Коэффициент")
ITEM_ALWAYS = ("НомерСтроки", "Наименование", "Количество")


def _number(value):
    """Рядок -> число (int, якщо ціле) або None."""
    d = checks.to_decimal(value)
    if d is None:
        return None
    return int(d) if d == d.to_integral_value() else float(d)


def _iso(date_text):
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", (date_text or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}T00:00:00" if m else None


def _party(info, key):
    party = {"Наименование": info.get(key, "")}
    code = info.get(f"{key}: код", "")
    m = re.match(r"(ЄДРПОУ|ІПН)\s+(\d+)", code)
    if m:
        party["ЕДРПОУ" if m.group(1) == "ЄДРПОУ" else "ИНН"] = m.group(2)
    m = re.match(r"ІПН\s+(\d+)", info.get(f"{key}: ІПН", ""))
    if m:
        party["ИНН"] = m.group(1)
    if info.get(f"{key}: IBAN"):
        party["IBAN"] = info[f"{key}: IBAN"]
    return party if party["Наименование"] or len(party) > 1 else None


def parse_contract(text):
    """'№ 64 від 01.03.2023' -> {'Представление', 'Номер', 'Дата'} (Дата ISO; рік із двох цифр теж розпізнається)."""
    text = (text or "").strip()
    if not text:
        return None
    contract = {"Представление": text}
    m = re.search(r"№\s*(.+?)\s+(?:від|вiд|от)\s+\d", text) or re.search(r"№\s*([^\s,;]+)", text)
    if m:
        contract["Номер"] = m.group(1).strip()
    date = docinfo.parse_date(text)
    if not date:
        m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{2})\b", text)
        if m:
            date = f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.20{m.group(3)}"
    iso = _iso(date)
    if iso:
        contract["Дата"] = iso
    return contract


def build_header(pairs):
    info = dict(pairs)
    header = {}
    if info.get("Документ"):
        header["ВидДокумента"] = info["Документ"]
    number = info.get("Номер") or info.get("Номер (з назви файлу)")
    if number:
        header["Номер"] = number
    date = info.get("Дата") or info.get("Дата (з назви файлу)")
    if date:
        header["ДатаТекст"] = date
        if _iso(date):
            header["Дата"] = _iso(date)
    for key, name in (("Постачальник", "Поставщик"), ("Покупець", "Покупатель")):
        party = _party(info, key)
        if party:
            header[name] = party
    contract = parse_contract(info.get("Договір"))
    if contract:
        header["Договор"] = contract
    if info.get("Склад"):
        header["Склад"] = info["Склад"]
    if info.get("Адреса доставки"):
        header["АдресДоставки"] = info["Адреса доставки"]
    totals = {}
    for key, name in (("Разом", "Сумма"), ("ПДВ", "СуммаНДС"), ("Разом з ПДВ", "СуммаСНДС")):
        value = _number(info.get(key))
        if value is not None:
            totals[name] = value
    if info.get("Кількість найменувань", "").isdigit():
        totals["КоличествоПозиций"] = int(info["Кількість найменувань"])
    if totals:
        header["Итоги"] = totals
    return header


def build_items(prepared, mapping, start=1):
    """Рядки товарів із підготовленої таблиці (заголовок + дані); нумерація продовжується з start."""
    items, _ = profiles.extract_items(prepared, mapping)
    result = []
    for n, raw in enumerate(items, start):
        qty_text, unit = profiles.split_quantity(raw.get("Количество", ""))
        values = dict(raw, Количество=qty_text)
        if unit and not str(values.get("Единица", "")).strip():
            values["Единица"] = unit
        item = {"НомерСтроки": n}
        for field in ITEM_TEXT_FIELDS:
            text = str(values.get(field, "") or "").strip()
            if text or field in ITEM_ALWAYS:
                item[field] = text
        for field in ITEM_NUMBER_FIELDS:
            text = str(values.get(field, "") or "").strip()
            if not text and field not in ITEM_ALWAYS:
                continue
            number = _number(text)
            item[field] = number if number is not None else (0 if not text else text)
        result.append(item)
    return result


def build_document(info_pairs, tables_data, source=None):
    """tables_data: [(prepared, mapping, name)] - обрані таблиці; їхні рядки об'єднуються в один список."""
    info = dict(info_pairs)
    goods, control = [], []
    for prepared, mapping, name in tables_data:
        if not prepared:
            continue
        goods += build_items(prepared, mapping, start=len(goods) + 1)
        for level, message in checks.run_checks(prepared, mapping, info):
            control.append({"Уровень": level, "Сообщение": message if len(tables_data) == 1 else f"{name}: {message}"})
    document = {
        "Формат": FORMAT_NAME,
        "ВерсияФормата": FORMAT_VERSION,
        "Источник": dict(source or {}),
        "Шапка": build_header(info_pairs),
        "Товары": goods,
        "Контроль": control,
    }
    extra = {}
    if info.get("Коди в тексті"):
        extra["КодыВТексте"] = info["Коди в тексті"]
    if info.get("IBAN у тексті"):
        extra["IBANВТексте"] = info["IBAN у тексті"]
    if extra:
        document["Дополнительно"] = extra
    return document


def write_json(document, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=1)
