"""
Профілі виходу для 1С-обробок імпорту: фіксована розкладка колонок, авто-підбір колонок
за заголовками, збереження вибору по постачальнику.
"""
import json
import os
import re
from decimal import Decimal, InvalidOperation

import converter

NO_PROFILE = "none"

PROFILES = {
    "upr": {
        "title": "УпрИмпортИзExcel (керовані форми)",
        "delimiter": ";",
        "fields": [
            "Код", "Артикул", "Штрихкод", "Наименование", "Комментарий", "Количество", "Единица",
            "УКТВЭД", "Вес", "Объем", "Высота", "Длина", "Ширина", "Коэффициент", "Цена", "Сумма",
            "ХарактеристикаНаименование",
        ],
    },
    "old": {
        "title": "ИмпортИзExcel (звичайні форми)",
        "delimiter": ";",
        "fields": [
            "НомерСтроки", "Код", "КодКонтрагента", "Артикул", "ШтрихКод", "НаименованиеКонтрагента",
            "Наименование", "Характеристика", "Серия", "ДопОписание", "Количество", "Единица", "УКТВЭД",
            "ВесЕдиницы", "ОбъемЕдиницы", "Коэффициент", "Цена", "Сумма", "ПроцентСкидкиНаценки",
        ],
    },
}

# Поля, які можна розпізнати за заголовками (канонічні назви; ШтрихКод/Штрихкод вважаємо одним полем)
_ALIASES = [
    ("Артикул", r"артикул|^арт\.?$|sku|article", None),
    ("Штрихкод", r"штрих|\bean\b|barcode", None),
    ("УКТВЭД", r"укт\s?зед|укт\s?вэд|уктвэд", None),
    ("Код", r"^код\b|^code$", r"єдрпоу|укт"),
    ("НомерСтроки", r"^№|^n$|^п/п|^#$|^no\.?$", None),
    ("Количество", r"к[іi]льк|кол-?во|количеств|к-сть|\bqty\b|quantity", r"_2$"),
    ("Единица", r"^од\.?$|одиниц|^ед\.?$|единиц|\bunit\b|^од\.? ?вим|^ед\.? ?изм", None),
    ("Цена", r"ц[іi]на|цена|price", None),
    ("Сумма", r"^сума|^сумма|^вс[іе]го|^всього|вартість|стоимость|amount|^total", r"пдв|ндс|vat"),
    ("ПроцентСкидкиНаценки", r"знижк|скидк|discount", None),
    ("Наименование", r"товар|найменув|назва|наименов|номенклатур|опис|description|\bname\b|послуг", None),
]
_UNIT_RE = re.compile(
    r"^(шт|кг|г|л|мл|м|м2|м3|упак|уп|пач|компл|пар|рул|бут|кор|пак|од|уп\.|шт\.|кг\.|м\.|л\.)\.?$", re.I
)
_TOTAL_RE = re.compile(r"^\s*(разом|всього|итого|всего|total)\b", re.I)
_QTY_UNIT_RE = re.compile(r"^\s*([+-]?[\d  ]+(?:[.,]\d+)?)\s*([^\d\s.,].*)$")

_CANON = {"ШтрихКод": "Штрихкод"}


def canon(field):
    return _CANON.get(field, field)


def profile_fields(profile_key):
    return PROFILES[profile_key]["fields"] if profile_key in PROFILES else None


def detectable_fields(profile_key):
    """Поля профілю, які можна підібрати з документа (у порядку профілю)."""
    known = {a[0] for a in _ALIASES}
    if profile_key not in PROFILES:
        return [a[0] for a in _ALIASES if a[0] != "ПроцентСкидкиНаценки"]
    return [f for f in PROFILES[profile_key]["fields"] if canon(f) in known]


def detect_mapping(headers, data_rows, fields):
    """{поле: назва_заголовка або None}: за регулярками, потім за вмістом колонок."""
    heads = [str(h or "").strip() for h in headers]
    low = [h.lower() for h in heads]
    wanted = {canon(f): f for f in fields}
    used, result = set(), {f: None for f in fields}

    def assign(field, i):
        used.add(i)
        result[wanted[field]] = heads[i]

    for field, include, exclude in _ALIASES:
        if field not in wanted or result[wanted[field]]:
            continue
        for i, h in enumerate(low):
            if i in used or not h:
                continue
            if field == "Единица" and re.search(r"(к[іi]льк\w*|кол\w*|qty)_2$", h):
                assign(field, i)
                break
            if re.search(include, h) and not (exclude and re.search(exclude, h)):
                assign(field, i)
                break

    def column(i):
        return [str(r[i]).strip() for r in data_rows if i < len(r) and str(r[i]).strip()]

    if "Единица" in wanted and not result[wanted["Единица"]]:
        for i in range(len(heads)):
            col = column(i)
            if i not in used and col and sum(1 for v in col if _UNIT_RE.match(v)) / len(col) >= 0.7:
                assign("Единица", i)
                break
    if "НомерСтроки" in wanted and not result[wanted["НомерСтроки"]] and heads:
        col = column(0)
        if 0 not in used and col and [v for v in col][:3] == ["1", "2", "3"][: min(3, len(col))]:
            assign("НомерСтроки", 0)
    if "Наименование" in wanted and not result[wanted["Наименование"]]:
        best, best_len = None, 0
        for i in range(len(heads)):
            col = column(i)
            if i in used or not col:
                continue
            avg = sum(len(v) for v in col) / len(col)
            if avg > best_len and any(re.search(r"[A-Za-zА-Яа-яІіЇїЄє]", v) for v in col):
                best, best_len = i, avg
        if best is not None and best_len >= 6:
            assign("Наименование", best)
    return result


# ------------------------------------------------------------------ збереження вибору по постачальнику

def _config_file():
    base = os.environ.get("TC_CONFIG_DIR") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "TableConverter"
    )
    return os.path.join(base, "profiles.json")


def _read_all():
    try:
        with open(_config_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _key(supplier_key, profile_key):
    return f"{supplier_key or '*'}|{profile_key}"


def load_saved(supplier_key, profile_key):
    return _read_all().get(_key(supplier_key, profile_key))


def save_mapping(supplier_key, profile_key, mapping):
    data = _read_all()
    data[_key(supplier_key, profile_key)] = {f: h for f, h in mapping.items()}
    path = _config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def resolve_mapping(headers, data_rows, profile_key, supplier_key=""):
    """Авто-підбір, поверх нього - збережене для постачальника (якщо такі заголовки є в таблиці)."""
    fields = detectable_fields(profile_key)
    mapping = detect_mapping(headers, data_rows, fields)
    saved = load_saved(supplier_key, profile_key) or (load_saved("", profile_key) if supplier_key else None)
    if saved:
        names = {str(h or "").strip() for h in headers}
        for field, header in saved.items():
            if field in mapping and (header is None or header in names):
                mapping[field] = header
    return mapping


# ------------------------------------------------------------------ застосування

def split_quantity(value):
    """'1 шт' -> ('1', 'шт'); '1,000' -> ('1', None); нечислове лишається як є."""
    s = str(value or "").strip()
    unit = None
    m = _QTY_UNIT_RE.match(s)
    if m:
        s, unit = m.group(1), m.group(2).strip()
    n = converter.normalize_number(s).replace(" ", "").replace(" ", "")
    try:
        d = Decimal(n)
    except InvalidOperation:
        return str(value or "").strip(), None
    if d == d.to_integral_value():
        return str(int(d)), unit
    return format(d.normalize(), "f"), unit


def is_total_row(row, name_index):
    cell = row[name_index] if name_index is not None and name_index < len(row) else ""
    if not str(cell).strip():
        cell = next((c for c in row if str(c).strip()), "")
    return bool(_TOTAL_RE.match(str(cell)))


def column_index(headers, name):
    if name is None:
        return None
    for i, h in enumerate(headers):
        if str(h or "").strip() == name:
            return i
    return None


def extract_items(prepared, mapping):
    """Рядки даних як словники {поле: значення}; рядки-підсумки виключаються й повертаються окремо."""
    headers = prepared[0] if prepared else []
    idx = {canon(f): column_index(headers, h) for f, h in mapping.items()}
    items, totals = [], []
    for row in prepared[1:]:
        if all(not str(c).strip() for c in row):
            continue
        item = {f: (row[i] if i is not None and i < len(row) else "") for f, i in idx.items()}
        if is_total_row(row, idx.get("Наименование")):
            totals.append(item)
        else:
            items.append(item)
    return items, totals


def apply_profile(prepared, profile_key, mapping):
    """Рядки в розкладці профілю: заголовок, потім дані; кількість ціла, ціна й сума нормалізовані."""
    fields = PROFILES[profile_key]["fields"]
    items, _ = extract_items(prepared, mapping)
    out = [list(fields)]
    for item in items:
        row = []
        qty, unit = split_quantity(item.get("Количество", ""))
        for f in fields:
            v = item.get(canon(f), "")
            if canon(f) == "Количество":
                v = qty
            elif canon(f) == "Единица" and not str(v).strip() and unit:
                v = unit
            elif canon(f) in ("Цена", "Сумма"):
                v = converter.normalize_number(str(v)) if str(v).strip() else ""
            row.append(v)
        out.append(row)
    return out
