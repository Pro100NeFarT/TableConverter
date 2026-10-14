"""
Скани й фото: розпізнавання тексту (OCR) -> слова з координатами -> таблиці й реквізити
тим самим розбором, що й для PDF без ліній. Движок - вбудований Windows OCR (ocr_windows).
Результат OCR завжди треба перевіряти: вкладка «Контроль» ловить помилки цифр.
"""
import difflib
import os
import re

import checks
import converter
import ocr_rapid
import ocr_windows
import profiles
import sources
import ukfix

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
DPI = 200
MIN_DESKEW = 0.4   # градусів: менший нахил не виправляємо
MAX_DESKEW = 20.0

_DIGIT_CONFUSABLE = str.maketrans({"з": "3", "З": "3", "О": "0", "о": "0", "l": "1", "I": "1", "|": "1", "ј": "1"})
_NUMERIC_CELL = re.compile(r"^[0-9зЗОоlI|ј.,\s+-]+$")
_NUMBER = re.compile(r"^[+-]?\d[\d ]*(?:[.,]\d+)?$")
_NUMBER_SIGN = re.compile(r"^(?:NQ|N°|Nº|№)$")
_NUMBER_SIGN_BEFORE_DIGITS = re.compile(r"^(?:No|N2|N9|Nо)$")
_FORM_WORDS = {
    "name": ("найменування", "товари", "товар", "послуг", "послуги", "робіт", "назва", "опис", "наименование", "товары"),
    "qty": ("кількість", "кіл-сть", "количество", "кол-во"),
    "price": ("ціна", "цена"),
    "sum": ("сума", "вартість", "сумма", "стоимость"),
}
_TOTAL_LINE = re.compile(r"^\s*(разом|всього|усього|итого|всего|загальна\s+вартість|total)\b", re.IGNORECASE)
_UNIT_CELL = re.compile(r"^(?:\d{1,4}\s*)?[^\d\s.,]{1,6}\.?$")
_QTY_UNIT = re.compile(r"^(\d[\d\s.,]*?)\s*([^\d\s.,]\S{0,7})$")


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def fix_word(text):
    """Типові підміни рушія 'ru' для українського тексту: ј -> і, NQ -> №."""
    if _NUMBER_SIGN.match(text):
        return "№"
    text = text.replace("ј", "і").replace("Ј", "І")
    return re.sub(r"^'(?=[А-ЯІЇЄҐа-яіїєґ])", "І", text)


def fix_numeric_cell(cell):
    """'з 600,00' -> '3 600,00': у клітинках, що складаються з цифр і схожих літер, літери замінюються
    цифрами (лише якщо результат - коректне число)."""
    text = str(cell).strip()
    if not text or not any(c.isdigit() for c in text) and not re.fullmatch(r"[зЗОоlI|]+", text):
        return cell
    if not _NUMERIC_CELL.match(text):
        return cell
    fixed = text.translate(_DIGIT_CONFUSABLE)
    return fixed if _NUMBER.match(fixed) else cell


_LOOKALIKE = str.maketrans({
    "a": "а", "A": "А", "B": "В", "c": "с", "C": "С", "e": "е", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "o": "о", "O": "О", "p": "р", "P": "Р", "T": "Т", "x": "х", "X": "Х", "y": "у", "i": "і", "I": "І",
    "6": "б", "0": "о", "3": "з",
})
_HEADER_VOCABULARY = (
    "найменування", "робіт", "послуг", "товарів", "товари", "товар", "кількість", "ціна", "сума", "одиниця",
    "вартість", "назва", "артикул",
)


def fix_header_text(text):
    """Слова шапки, прочитані латинськими літерами-двійниками й цифрами ('p06iT' замість 'робіт'):
    замінюються лише коли після транслітерації слово збігається зі словником слів шапки."""
    def fix(match):
        token = match.group(0)
        if not re.search(r"[A-Za-z0-9]", token):
            return token
        mapped = token.translate(_LOOKALIKE)
        best = max(_HEADER_VOCABULARY, key=lambda w: difflib.SequenceMatcher(None, mapped.lower(), w).ratio())
        if difflib.SequenceMatcher(None, mapped.lower(), best).ratio() < 0.8:
            return token
        return best.capitalize() if token[0].isupper() else best

    return re.sub(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9']+", fix, text)


def fix_words(words):
    """Виправлення слів; 'N2'/'No' перед числом - знак номера (за координатами наступне слово в тому ж рядку)."""
    fixed = [dict(w, text=fix_word(w["text"])) for w in words]
    for w in fixed:
        if not _NUMBER_SIGN_BEFORE_DIGITS.match(w["text"]):
            continue
        nxt = min(
            (o for o in fixed if o is not w and o["x0"] >= w["x1"] - 2 and abs(o["top"] - w["top"]) < (w["bottom"] - w["top"])),
            key=lambda o: o["x0"],
            default=None,
        )
        if nxt is not None and nxt["text"].strip(" .").isdigit():
            w["text"] = "№"
    return fixed


_LOOKALIKE_LETTERS = {k: v for k, v in _LOOKALIKE.items() if not chr(k).isdigit()}
_LOOKALIKE_LETTERS[ord("t")] = "т"


_KNOWN_UNITS = ("шт", "кг", "г", "л", "мл", "м", "м2", "м3", "км", "см", "мм", "т", "год", "хв", "доба", "дн",
                "міс", "уп", "упак", "пач", "компл", "набір", "пар", "рул", "бут", "кор", "пак", "послуга", "послуг")


def fix_unit(unit):
    """Одиниця виміру після OCR: 'шT' -> 'шт', 'wт' -> 'шт', '1оо шт' -> '100 шт', 'род' -> 'год'."""
    unit = str(unit).strip().replace("w", "ш").replace("W", "Ш")
    if unit.lower() in ("et", "ет", "ят", "ut", "uт", "ur", "ит"):
        return "шт"
    if 1 < len(unit) <= 5 and not any(ch.isdigit() for ch in unit) and (unit.isupper() or unit.lower() in _KNOWN_UNITS):
        unit = unit.lower()  # ШТ, Шт -> шт
    m = re.match(r"^(\d[\d\s]*\s)?([^\d\s.,]{2,8})\.?$", unit)
    if m and m.group(2).lower() not in _KNOWN_UNITS and len(m.group(2)) >= 3:
        close = difflib.get_close_matches(m.group(2).lower(), _KNOWN_UNITS, n=2, cutoff=0.66)
        if len(close) == 1:  # лише коли найближча одиниця одна
            return f"{m.group(1) or ''}{close[0]}"
    if re.search(r"[A-Za-z]", unit):
        unit = unit.translate(_LOOKALIKE_LETTERS).lower()
    m = re.match(r"^([\dОоOo]{1,5})\s*([^\d\s.,]{1,6}\.?)$", unit)
    if m and re.search(r"\d", m.group(1).translate(_DIGIT_CONFUSABLE)):
        return f"{m.group(1).translate(_DIGIT_CONFUSABLE)} {m.group(2)}"
    return unit


def fix_mixed_script(text):
    """Слова з кирилиці з окремими латинськими літерами ('вiд', 'BД') - латинські літери замінюються
    кириличними двійниками."""
    def fix(match):
        token = match.group(0)
        cyr = len(re.findall(r"[А-Яа-яІіЇїЄєҐґ]", token))
        lat = len(re.findall(r"[A-Za-z]", token))
        return token.translate(_LOOKALIKE_LETTERS) if cyr and lat and lat <= cyr else token

    return re.sub(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]+", fix, text)


def fix_rows(rows):
    return [[fix_numeric_cell(c) for c in row] for row in rows]


def resolve_engine(engine="auto"):
    """'auto': рушій для української (RapidOCR), якщо встановлений, інакше вбудований Windows OCR."""
    if engine == "auto":
        return "rapid" if ocr_rapid.is_installed() else "windows"
    return engine


def recognize_image(img, lang="uk", engine="auto", contrast=False):
    """Слова зображення з виправленням нахилу. Повертає (слова, інфо); інфо['engine'] - 'rapid' або 'windows'.
    Windows OCR: якщо бачить кут тексту, зображення вирівнюється й розпізнається вдруге; RapidOCR вирівнює сам."""
    from PIL import Image

    if resolve_engine(engine) == "rapid":
        words, info = ocr_rapid.recognize(img, contrast=contrast)
        info["engine_kind"] = "rapid"
        return words, info
    words, info = ocr_windows.recognize(img, lang)
    info["engine_kind"] = "windows"
    angle = info.get("angle")
    if angle is not None and MIN_DESKEW <= abs(angle) <= MAX_DESKEW:
        straight = img.rotate(angle, expand=True, fillcolor="white", resample=Image.BICUBIC)
        words2, info2 = ocr_windows.recognize(straight, lang)
        if len(words2) >= len(words):
            words, info = words2, info2
    info["engine_kind"] = "windows"
    return fix_words(words), info


def infer_missing_quantities(tables):
    """Кількість або сума, яку OCR не прочитав (дрібний текст поруч із рамкою), обчислюється з двох інших
    (сума ÷ ціна, кількість × ціна), якщо вийшло чисте число. Повертає примітку з номерами рядків або None."""
    qty_rows, sum_rows = [], []
    for table in tables:
        if "за заголовком" not in table.name or len(table.rows) < 2:
            continue
        header = [str(h) for h in table.rows[0]]
        price_i = next((i for i, h in enumerate(header) if h.startswith("Ціна")), None)
        sum_i = next((i for i, h in enumerate(header) if h.startswith("Сума")), None)
        qty_i = next((i for i, h in enumerate(header) if h.startswith("Кількість")), None)
        if None in (price_i, sum_i, qty_i):
            continue
        for number, row in enumerate(table.rows[1:], 1):
            qty, price, total = (checks.to_decimal(row[i]) for i in (qty_i, price_i, sum_i))
            if not str(row[qty_i]).strip() and price and total is not None:
                value = total / price
                if abs(value - value.to_integral_value()) <= checks.Decimal("0.0005") and value > 0:
                    row[qty_i] = str(int(value.to_integral_value()))
                    qty_rows.append(number)
            elif not str(row[sum_i]).strip() and qty and price:
                row[sum_i] = format((qty * price).quantize(checks.Decimal("0.01")), "f")
                sum_rows.append(number)
    parts = []
    if qty_rows:
        parts.append("Кількість у рядках " + ", ".join(map(str, qty_rows)) + " не розпізнано й обчислена як сума ÷ ціна")
    if sum_rows:
        parts.append("сума в рядках " + ", ".join(map(str, sum_rows)) + " не розпізнана й обчислена як кількість × ціна")
    return ("; ".join(parts)[0].upper() + "; ".join(parts)[1:] + " — перевірте.") if parts else None


def weak_rows(table):
    """Номери (з 1) рядків даних, які OCR міг прочитати погано: порожня чи дуже коротка назва, немає коду, коли в
    інших рядках він є, кількість × ціна ≠ сума."""
    header = [str(h) for h in table.rows[0]]
    rows = table.rows[1:]
    name_i = 2 if header[1:2] == ["Код"] else 1
    code_share = sum(1 for r in rows if header[1:2] == ["Код"] and str(r[1]).strip()) / max(len(rows), 1)
    qty_i = next((i for i, h in enumerate(header) if h.startswith("Кількість")), None)
    price_i = next((i for i, h in enumerate(header) if h.startswith("Ціна")), None)
    sum_i = next((i for i, h in enumerate(header) if h.startswith("Сума")), None)
    weak = []
    for number, row in enumerate(rows, 1):
        bad = len(str(row[name_i]).strip()) < 10
        if header[1:2] == ["Код"] and code_share >= 0.6 and not str(row[1]).strip():
            bad = True
        if None not in (qty_i, price_i, sum_i):
            qty = checks.to_decimal(profiles.split_quantity(row[qty_i])[0])
            price, total = checks.to_decimal(row[price_i]), checks.to_decimal(row[sum_i])
            if qty is not None and price is not None and total is not None:
                diff = abs(qty * price - total)
                if diff > checks.Decimal("0.02") and diff > abs(total) * checks.Decimal("0.005"):
                    bad = True
        if bad:
            weak.append(number)
    return weak


def reocr_weak_rows(img, words, tables, lang="uk", engine="auto", max_rows=12):
    """Рядки таблиці з поганим розпізнаванням (OCR інколи губить довгі рядки поруч із рамкою таблиці) розпізнаються
    окремо: смуга зображення рядка вирізається (у натуральному розмірі й збільшена втричі) і замінює слова цього
    рядка, якщо від цього стає менше слабких рядків. Повертає (слова, [номери виправлених рядків])."""
    table = next((t for t in tables if t.selected and t.spans), None)
    if table is None or resolve_engine(engine) != "rapid":
        return words, []
    weak = weak_rows(table)[:max_rows]
    if not weak:
        return words, []
    margin = 6
    bands = []
    for number in weak:
        top, bottom = table.spans[number - 1]
        bands.append((number, max(0, int(top) - margin), min(img.height, int(bottom) + margin), int(top), int(bottom)))
    crops, plan = [], []
    for number, y0, y1, top, bottom in bands:
        crop = img.crop((0, y0, img.width, y1))
        for scale in (1, 3):
            crops.append(crop.resize((crop.width * scale, crop.height * scale)) if scale > 1 else crop)
            plan.append((number, y0, y1, top, bottom, scale))
    try:
        results = ocr_rapid.recognize_many(crops)
    except Exception:
        return words, []
    current, fixed = words, []
    by_row = {}
    for (number, y0, y1, top, bottom, scale), (new_words, _info) in zip(plan, results):
        by_row.setdefault(number, []).append((y0, top, bottom, scale, new_words))
    for number, variants in by_row.items():
        base_weak = len(weak_rows(next(t for t in tables_from_image_words(current, "x") if t.selected)))
        best, best_weak = None, base_weak
        for y0, top, bottom, scale, new_words in variants:
            mapped = []
            for w in new_words:
                cy = y0 + (w["top"] + w["bottom"]) / 2 / scale
                if top - 2 <= cy <= bottom + 2:
                    mapped.append(dict(w, x0=w["x0"] / scale, x1=w["x1"] / scale, top=y0 + w["top"] / scale,
                                       bottom=y0 + w["bottom"] / scale))
            kept = [w for w in current if not (top - 2 <= (w["top"] + w["bottom"]) / 2 <= bottom + 2)]
            candidate = kept + mapped
            try:
                cand_table = next((t for t in tables_from_image_words(candidate, "x") if t.selected), None)
            except Exception:
                continue
            if cand_table is None:
                continue
            cand_weak = len(weak_rows(cand_table))
            if cand_weak < best_weak and len(cand_table.rows) >= len(table.rows):
                best, best_weak = candidate, cand_weak
        if best is not None:
            current = best
            fixed.append(number)
    return current, fixed


def table_stats(tables):
    """(узгоджених рядків, усього рядків) обраної таблиці: кількість, ціна й сума - числа, кількість × ціна = сума."""
    table = next((t for t in tables if t.selected), None)
    if table is None:
        return 0, 0
    prepared = converter.prepare_rows(table.rows, table.merges, flatten_newlines=True, trim_trailing_empty=True,
                                      sanitize_quotes=False, fill_merges=True, normalize_numbers=False)
    if len(prepared) < 2:
        return 0, 0
    mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr")
    items, _ = profiles.extract_items(prepared, mapping)
    if not items:
        return 0, 0
    good = 0
    for item in items:
        qty = checks.to_decimal(profiles.split_quantity(item.get("Количество", ""))[0])
        price, total = checks.to_decimal(item.get("Цена")), checks.to_decimal(item.get("Сумма"))
        if qty is None or price is None or total is None:
            continue
        diff = abs(qty * price - total)
        if diff <= checks.Decimal("0.02") or diff <= abs(total) * checks.Decimal("0.005"):
            good += 1
    return good, len(items)


def table_quality(tables):
    """0..1: частка узгоджених рядків обраної таблиці; 1 - таблицю знайдено й вона узгоджена; 0 - таблиці немає."""
    good, total = table_stats(tables)
    return good / total if total else 0.0


def recognize_best(img, lang="uk", engine="auto", first_page=True):
    """Слова зображення; коли таблиця не знайдена або її числа не узгоджуються (кількість × ціна ≠ сума),
    зображення розпізнається ще раз із вирівняним контрастом і береться кращий результат.
    Повертає (слова, інфо, примітка про виправлення за словником або None)."""
    words, info = recognize_image(img, lang, engine)
    words, note = correct_ukrainian(words)
    if resolve_engine(engine) != "rapid":
        return words, info, note
    tables = tables_from_image_words(words, "x")
    quality = table_quality(tables)
    if quality < 1 and not (quality == 0 and not first_page):
        words2, info2 = recognize_image(img, lang, engine, contrast=True)
        words2, note2 = correct_ukrainian(words2)
        tables2 = tables_from_image_words(words2, "x")
        if table_stats(tables2) > table_stats(tables):
            words, info, note, tables = words2, info2, note2, tables2
    words, redone = reocr_weak_rows(img, words, tables, lang, engine)
    if redone:
        words, note3 = correct_ukrainian(words)
        extra = "Рядки " + ", ".join(map(str, redone)) + " розпізнано окремо (погано читалися разом з рамкою таблиці)."
        note = (note + " " + extra) if note else extra
    return words, info, note


def lines_from_words(words):
    """Текст сторінки по рядках для зчитування реквізитів (комірки розділені табуляцією). Рядок із двома-трьома
    сумами одразу під таблицею (без підпису) стає 'Разом: без ПДВ з ПДВ'."""
    lines, seen_table = [], False
    for _, cells in sources._line_cells_from_words(words):
        texts = [str(fix_numeric_cell(c[2])).strip() for c in cells]
        numeric = [_is_number(t) for t in texts]
        if all(numeric) and 2 <= len(texts) <= 3 and all(re.search(r"[.,]\d{2}$", t) for t in texts) and seen_table:
            lines.append("Разом: " + " ".join(texts))
            seen_table = False
            continue
        if sum(numeric) >= 4:
            seen_table = True
        line = fix_mixed_script("\t".join(c[2] for c in cells))
        line = re.sub(r"\b[вВ][ИиIі]д\b(?=\s+\d{1,2}[./]\d{1,2}[./]\d{2,4})", "від", line)
        lines.append(re.sub(r"(№\s*)([А-ЯІЇЄA-Z][а-яіїєa-z]{1,3})(?=[-/]?\d)", lambda m: m.group(1) + m.group(2).upper(), line))
    return lines


def _fuzzy_any(text, words, threshold=0.72):
    tokens = re.findall(r"[а-яіїєґ'a-z0-9-]{3,}", text.lower())
    return any(difflib.SequenceMatcher(None, t, w).ratio() >= threshold for t in tokens for w in words)


def _is_number(text):
    return bool(_NUMBER.match(text.replace("\u00a0", " ").strip()))


def _header_groups(texts):
    """Порядок числових колонок за словами шапки: ['qty', 'price', 'price', 'sum', 'sum'] ('Кількість Ціна без
    Ціна з Сума без Сума з')."""
    order = []
    for token in re.findall(r"[а-яіїєґ'a-z0-9-]{3,}", " ".join(texts).lower()):
        for group in ("qty", "price", "sum"):
            if any(difflib.SequenceMatcher(None, token, w).ratio() >= 0.72 for w in _FORM_WORDS[group]):
                order.append(group)
                break
    return order


def _numeric_header(order, labels=None):
    """Назви колонок: одна ціна/сума - 'Ціна', 'Сума'; дві - 'без ПДВ' і 'з ПДВ' (порядок - за підписами шапки, якщо
    відомі); більше - з номером."""
    names = []
    for group, base in (("price", "Ціна"), ("sum", "Сума")):
        count = order.count(group)
        picked = [lab for g, lab in zip(order, labels or [""] * len(order)) if g == group]
        if count == 1:
            names.append(base)
        elif count == 2 and picked == ["vat", "no_vat"]:
            names += [f"{base} з ПДВ", f"{base} без ПДВ"]
        elif count == 2:
            names += [f"{base} без ПДВ", f"{base} з ПДВ"]
        else:
            names += [base if k == 0 else f"{base}_{k + 1}" for k in range(count)]
    return names


def _parse_form_row(cells, expected, next_index=None):
    """Рядок таблиці-форми за вмістом: [№, назва, кількість, одиниця, ціни..., суми...] або None (немає чисел).
    expected - порядок числових колонок шапки ('qty', 'price', 'sum'...); зайві числа ліворуч (як '100' в
    одиниці '100 шт') належать одиниці."""
    items = []  # (x0, 'num'|'text', значення)
    glued = {}  # x0 числа -> '100 шт'
    for x0, _x1, text in cells:
        fixed = str(fix_numeric_cell(text)).strip()
        if _PERCENT.match(fixed):
            continue  # ставка ПДВ
        m = _QTY_UNIT.match(fixed)
        if m and _is_number(m.group(1)):
            items.append((x0, "num", m.group(1).strip()))
            items.append((x0 + 1, "text", m.group(2)))
            glued[x0] = f"{m.group(1).strip()} {m.group(2)}"
        elif _is_number(fixed):
            items.append((x0, "num", fixed))
        else:
            items.append((x0, "text", text.strip()))
    index = ""
    if len(items) >= 3 and items[0][1] == "num" and re.fullmatch(r"\d{1,3}", items[0][2]):
        index = items.pop(0)[2]
    elif items and items[0][1] == "text" and next_index is not None:
        m = re.match(rf"^{next_index}\s+(\S.*)$", items[0][2])
        if m and any(i[1] == "num" for i in items[1:]):
            index = str(next_index)
            items[0] = (items[0][0], "text", m.group(1))
    numbers = [i for i in items if i[1] == "num"]
    if not numbers:
        return None
    need = len(expected)
    unit = ""
    if need >= 4 and len(numbers) > need:
        extra = numbers[: len(numbers) - need]
        numbers = numbers[len(numbers) - need:]
        if extra[0][0] in glued:
            unit = glued[extra[0][0]]
            items = [i for i in items if not (i[0] == extra[0][0] + 1 and i[1] == "text")]
        targets = list(expected)
    elif len(numbers) == need and "sum" in expected:  # без 'Сума' у шапці (OCR) розподіл за кількістю чисел
        targets = list(expected)
    else:
        count = min(len(numbers), 3)
        targets = ["qty", "price", "sum"][-count:] if count > 2 else ["price", "sum"][-count:]
        numbers = numbers[-len(targets):]
    values = {"qty": "", "price": [], "sum": []}
    for group, n in zip(targets, numbers):
        if group == "qty":
            values["qty"] = n[2]
        else:
            values[group].append(n[2])
    texts = [i for i in items if i[1] == "text"]
    if not unit:
        for t in texts[1:]:
            if len(t[2]) <= 8 and (not any(ch.isdigit() for ch in t[2]) or _UNIT_CELL.match(t[2])):
                unit = t[2]
                break
    name = " ".join(t[2] for t in texts if t[2] != unit or t is texts[0])
    n_price = max(sum(1 for g in expected if g == "price"), len(values["price"]), 1)
    n_sum = max(sum(1 for g in expected if g == "sum"), len(values["sum"]), 1)
    prices = (values["price"] + [""] * n_price)[:n_price]
    sums = (values["sum"] + [""] * n_sum)[:n_sum]
    return [index, name.strip(), values["qty"], unit, *prices, *sums]


_PERCENT = re.compile(r"^\d{1,2}\s?%$")
_CODE_PREFIX = re.compile(r"^([А-Яа-яІіЇїЄєA-Za-z]{2,3})\s?[-–]\s?([0-9оОOl]{3,}(?:\s\d{3,4})?)\s*(?=\S)")


def _numeric_cells(cells):
    """Числові комірки рядка: (індекс, центр числа, x0, x1, число, одиниця, злита з числом, або None)."""
    out = []
    for i, (x0, x1, text) in enumerate(cells):
        fixed = str(fix_numeric_cell(text)).strip()
        if _PERCENT.match(fixed):
            continue  # ставка ПДВ
        lead = re.match(r"^(\d[\d\s]*[.,]\d{2,3})\s+([^\d\s].*)$", fixed)
        if lead and _is_number(lead.group(1)):  # '6346,00 реставрація ...': число злилося з текстом сусідньої колонки
            share = len(lead.group(1)) / max(len(fixed), 1)
            rest = lead.group(2).strip()
            out.append((i, x0 + (x1 - x0) * share / 2, x0, x1, lead.group(1).strip(),
                        rest if len(rest) <= 8 and not any(ch.isdigit() for ch in rest) else None))
            continue
        m = _QTY_UNIT.match(fixed)
        if m and _is_number(m.group(1)):
            share = len(m.group(1)) / max(len(fixed), 1)
            out.append((i, x0 + (x1 - x0) * share / 2, x0, x1, m.group(1).strip(), m.group(2)))
        elif _is_number(fixed):
            out.append((i, (x0 + x1) / 2, x0, x1, fixed, None))
    return out


def _assign(numeric, anchors, tol):
    """{індекс якоря: числова комірка}: найближчі пари 'комірка - якір' у межах допуску."""
    pairs = sorted(
        (abs(a[1] - n[1]), ai, ni)
        for ni, n in enumerate(numeric) for ai, a in enumerate(anchors) if abs(a[1] - n[1]) <= tol
    )
    values, used = {}, set()
    for _dist, ai, ni in pairs:
        if ai not in values and ni not in used:
            values[ai] = numeric[ni]
            used.add(ni)
    return values


def _header_anchors(line_words):
    anchors = []
    for w in sorted(line_words, key=lambda w: w["x0"]):
        token = re.sub(r"[^а-яіїєґa-z'-]", "", w["text"].lower())
        if len(token) < 3:
            continue
        for group in ("qty", "price", "sum"):
            if any(difflib.SequenceMatcher(None, token, k).ratio() >= 0.72 for k in _FORM_WORDS[group]):
                anchors.append([group, (w["x0"] + w["x1"]) / 2, w["x1"]])
                break
    ordered = sorted(line_words, key=lambda w: w["x0"])
    for anchor in anchors:  # слова після ключового слова до наступного ключового: 'без' / 'з' ПДВ
        following = [w["text"].lower() for w in ordered if w["x0"] >= anchor[2] - 1][:2]
        nxt = [a[1] for a in anchors if a[1] > anchor[1]]
        following = [t for t, w in zip(following, [w for w in ordered if w["x0"] >= anchor[2] - 1][:2])
                     if not nxt or (w["x0"] + w["x1"]) / 2 < nxt[0] - 5]
        anchor.append("no_vat" if any(t.startswith("без") for t in following)
                      else "vat" if any(re.fullmatch(r"(з|із|зі|с)", t) for t in following) else "")
    return anchors


def _anchored_rows(lines, h, anchors, page_width):
    """Рядки таблиці за позиціями слів шапки: числа розкладаються по найближчих колонках (кількість, ціни, суми),
    зайві колонки праворуч і ставки ПДВ відкидаються. Повертає (рядки, групи колонок) або (None, None)."""
    tol = max(30.0, 0.07 * page_width)
    first = h + 1
    # уточнення якорів за даними: медіана центрів чисел, що потрапили в колонку
    centers = {i: [] for i in range(len(anchors))}
    for _t, cells, _w in lines[first:first + 80]:
        if _TOTAL_LINE.match(" ".join(c[2] for c in cells)):
            break
        numeric = _numeric_cells(cells)
        if len(numeric) < 2:
            continue
        for ai, n in _assign(numeric, anchors, tol).items():
            centers[ai].append(n[1])
    refined = [[a[0], sorted(centers[i])[len(centers[i]) // 2] if len(centers[i]) >= 2 else a[1], *a[2:]]
               for i, a in enumerate(anchors)]
    anchors = refined
    left_edge = min(a[1] for a in anchors) - tol
    right_edge = max(a[1] for a in anchors) + tol

    rows, groups, labels = [], [a[0] for a in anchors], [a[3] if len(a) > 3 else "" for a in anchors]
    spans = []
    for _t, cells, _w in lines[first:]:
        if _TOTAL_LINE.match(" ".join(c[2] for c in cells)):
            break
        numeric = _numeric_cells(cells)
        values = _assign(numeric, anchors, tol)
        index, texts, consumed = "", [], {n[0] for n in values.values()}
        for i, (x0, x1, text) in enumerate(cells):
            if i in consumed or _PERCENT.match(text.strip()):
                continue
            if x0 > right_edge:
                continue  # додаткові колонки праворуч (вхідний номер тощо)
            texts.append((x0, x1, text.strip()))
        if len(values) < 2:
            if rows and texts and not values and all(t[1] < left_edge + tol for t in texts):
                rows[-1][1] = f"{rows[-1][1]} {' '.join(t[2] for t in texts)}".strip()  # продовження назви
                spans[-1] = (spans[-1][0], max(spans[-1][1], max(w["bottom"] for w in _w)))
                continue
            if rows:
                break
            continue
        if texts and re.fullmatch(r"\d{1,3}", texts[0][2]) and len(rows) + 1 == int(texts[0][2]):
            index = texts.pop(0)[2]
        elif texts:
            m = re.match(rf"^{len(rows) + 1}\s+(\S.*)$", texts[0][2])
            if m:
                index = str(len(rows) + 1)
                texts[0] = (texts[0][0], texts[0][1], m.group(1))
        qty_ai = next((i for i, a in enumerate(anchors) if a[0] == "qty"), None)
        unit = ""
        if qty_ai in values and values[qty_ai][5]:
            unit = values[qty_ai][5]
        else:
            for t in texts[1:]:
                if len(t[2]) <= 8 and (not any(ch.isdigit() for ch in t[2]) or _UNIT_CELL.match(t[2])):
                    unit = t[2]
                    texts.remove(t)
                    break
        name = " ".join(t[2] for t in texts).strip()
        if rows and not index and not name:
            break  # рядок підсумків без підпису
        qty = values[qty_ai][4] if qty_ai in values else ""
        prices = [values[i][4] if i in values else "" for i, a in enumerate(anchors) if a[0] == "price"]
        sums = [values[i][4] if i in values else "" for i, a in enumerate(anchors) if a[0] == "sum"]
        if re.fullmatch(r"\d{1,3}\s\d{3}", qty) and unit:
            # '160 100 шт': кількість 160 і упаковка '100 шт', а не 160100 (перевірка за ціною й сумою)
            first, second = qty.split()
            for p, sm in zip(prices, sums):
                p, sm = checks.to_decimal(p), checks.to_decimal(sm)
                if p and sm and abs(checks.Decimal(first) * p - sm) <= max(checks.Decimal("0.02"), abs(sm) * checks.Decimal("0.005"))                         and abs(checks.Decimal(first + second) * p - sm) > abs(sm) * checks.Decimal("0.005"):
                    qty, unit = first, f"{second} {unit}"
                    break
        rows.append([index, name, qty, unit, *prices, *sums])
        spans.append((min(w["top"] for w in _w), max(w["bottom"] for w in _w)))
    return (rows, groups, labels, spans) if rows else (None, None, None, None)


def _split_codes(header_cells, rows):
    """Колонка 'Код' у шапці: код на початку назви ('НФ-00000256 Люк...') виноситься в окрему колонку."""
    if not any(re.fullmatch(r"код\.?", c[2].strip().lower()) for c in header_cells):
        return None
    parts = []
    for r in rows:
        m = _CODE_PREFIX.match(r[1])
        parts.append((m, r))
    if sum(1 for m, _ in parts if m) < max(2, len(rows) * 0.6):
        return None
    codes = []
    numbers = [re.sub(r"[оОOl]", lambda x: "1" if x.group(0) == "l" else "0", m.group(2)).replace(" ", "") for m, _ in parts if m]
    common = max(set(map(len, numbers)), key=list(map(len, numbers)).count)
    for m, r in parts:
        if m:
            digits = re.sub(r"[оОOl]", lambda x: "1" if x.group(0) == "l" else "0", m.group(2)).replace(" ", "")
            digits = digits[-common:] if len(digits) > common else digits  # зайва цифра від літери 'о' перед номером
            codes.append(f"{m.group(1).upper()}-{digits}")
            r[1] = r[1][m.end():].lstrip('|.! ').strip()
        else:
            codes.append("")
    return codes


def form_table_from_words(words, name):
    """Таблиця друкованої форми (акт, рахунок) за заголовком і вмістом: знаходить рядок шапки за ключовими
    словами (з допуском на помилки OCR; достатньо 'Найменування' + 'Сума'), потім рядки з числами до
    рядка 'Разом'. Працює й для таблиці з одним рядком і для кількох колонок цін/сум (без ПДВ / з ПДВ);
    назва товару на кілька рядків склеюється. Назви колонок канонічні."""
    lines3 = sources._line_cells_from_words(words, with_words=True)
    lines = [(t, c) for t, c, _w in lines3]
    page_width = max((w["x1"] for w in words), default=1000)
    for h, (_top, cells) in enumerate(lines):
        groups = {g for g, ws in _FORM_WORDS.items() if any(_fuzzy_any(c[2], ws) for c in cells)}
        numeric_groups = groups & {"qty", "price", "sum"}
        # назва товару в шапці може не розпізнатися - тоді достатньо двох із трьох: кількість, ціна, сума
        if len(cells) < 2 or not numeric_groups or ("name" not in groups and len(numeric_groups) < 2):
            continue
        order = _header_groups([c[2] for c in cells])
        if len(order) >= 4 and order.count("qty") == 1:  # кілька колонок цін/сум (без ПДВ / з ПДВ)
            expected, out_groups = tuple(order), list(order)
        else:
            expected, out_groups = tuple(g for g in ("qty", "price", "sum") if g in groups), ["qty", "price", "sum"]
        rows, name_x, out_labels, out_spans = [], None, None, []
        for _t, row_cells in lines[h + 1:]:
            if _TOTAL_LINE.match(" ".join(c[2] for c in row_cells)):
                break
            parsed = _parse_form_row(row_cells, expected, len(rows) + 1)
            if parsed and rows and not parsed[0] and not parsed[1]:
                break  # рядок підсумків без назви (суми під таблицею)
            if parsed:
                rows.append(parsed)
                lead = row_cells[1] if len(row_cells) > 1 and re.fullmatch(r"\d{1,3}", row_cells[0][2].strip()) else row_cells[0]
                name_x = lead[0]
                continue
            if rows and len(row_cells) == 1 and name_x is not None and abs(row_cells[0][0] - name_x) <= 80:
                rows[-1][1] = f"{rows[-1][1]} {row_cells[0][2]}".strip()
                continue
            if rows:
                break
        anchors = _header_anchors(lines3[h][2])
        a_rows, a_groups, a_labels, a_spans = (None, None, None, None)
        if len(anchors) >= 2:
            a_rows, a_groups, a_labels, a_spans = _anchored_rows(lines3, h, anchors, page_width)
        if a_rows:  # за позиціями колонок шапки; береться, якщо дає не гірший результат, ніж розбір за вмістом
            name_cell = next((c[2] for c in cells if _fuzzy_any(c[2], _FORM_WORDS["name"])), "Найменування")
            header_a = ["№", fix_header_text(name_cell), "Кількість", "Од."] + _numeric_header(a_groups, a_labels)
            table_a = sources.Table(f"{name}, табл. 1 (за заголовком)", [header_a] + [(r + [""] * len(header_a))[:len(header_a)] for r in a_rows])
            if not rows:
                rows, out_groups, out_labels, out_spans = a_rows, a_groups, a_labels, a_spans
            else:
                header_l = ["№", fix_header_text(name_cell), "Кількість", "Од."] + _numeric_header(out_groups)
                table_l = sources.Table("x", [header_l] + [(r + [""] * len(header_l))[:len(header_l)] for r in rows])
                if (table_quality([table_a]) * len(a_rows), len(a_rows)) >= (table_quality([table_l]) * len(rows), len(rows)):
                    rows, out_groups, out_labels, out_spans = a_rows, a_groups, a_labels, a_spans
        if rows:
            name_cell = next((c[2] for c in cells if _fuzzy_any(c[2], _FORM_WORDS["name"])), "Найменування")
            name_cell = fix_header_text(name_cell)
            header = ["№", name_cell, "Кількість", "Од."] + _numeric_header(out_groups, out_labels)
            width = len(header)
            rows = [(r + [""] * width)[:width] for r in rows]
            for r in rows:
                r[3] = fix_unit(r[3])
                r[1] = re.sub(r"^[|.!\s]+", "", r[1])  # смуга рамки на початку назви
            counts = {}
            for r in rows:
                if r[3]:
                    counts[r[3]] = counts.get(r[3], 0) + 1
            if counts:  # одиниця, яку OCR не прочитав, - та сама, що в більшості рядків (від 80 %)
                common_unit, n_common = max(counts.items(), key=lambda kv: kv[1])
                if n_common >= 0.8 * sum(1 for r in rows) and common_unit in _KNOWN_UNITS:
                    for r in rows:
                        r[3] = r[3] or common_unit
            units = {r[3] for r in rows if r[3]}
            for r in rows:  # одиниця '100 шт', злита з назвою
                if not r[3]:
                    for u in units:
                        m = re.search(r"\s" + re.escape(u) + r"(?=\s|\(|$)", r[1])
                        if m:
                            r[3], r[1] = u, (r[1][: m.start()] + r[1][m.end():]).strip()
                            break
            codes = _split_codes(cells, rows)
            if codes:
                header = [header[0], "Код"] + header[1:]
                rows = [[r[0], c] + r[1:] for r, c in zip(rows, codes)]
            return sources.Table(f"{name}, табл. 1 (за заголовком)", [header] + rows, spans=list(out_spans or []))
    return None


def _numeric_ratio(rows):
    cells = [c for r in rows for c in r if str(c).strip()]
    return sum(1 for c in cells if _is_number(str(c))) / len(cells) if cells else 0.0


def tables_from_image_words(words, name):
    """Спершу таблиця форми за заголовком; інакше таблиці за вирівнюванням - обирається лише найбільш
    схожа на справжню (багато чисел, ≥3 рядків), решта лишається в списку, але не обирається."""
    form = form_table_from_words(words, name)
    if form:
        return [form]
    tables = [
        sources.Table(f"{name}, табл. {i}", fix_rows(rows))
        for i, rows in enumerate(sources.tables_from_words(words), 1)
    ]
    scored = [(t.n_rows * _numeric_ratio(t.rows), t) for t in tables if t.n_rows >= 3 and _numeric_ratio(t.rows) >= 0.25]
    best = max(scored, key=lambda x: x[0])[1] if scored else (max(tables, key=lambda t: t.n_rows) if tables else None)
    for t in tables:
        t.selected = t is best
    return tables


def correct_ukrainian(words):
    """Слова з виправленими за словником українськими літерами; (слова, примітка або None)."""
    words, changes = ukfix.fix_words(words)
    if not changes:
        return words, None
    sample = ", ".join(f"{a} → {b}" for a, b in list(dict.fromkeys(changes))[:3])
    return words, f"За словником виправлено українські літери: {len(changes)} ({sample})."


def notes_for(info):
    notes = ["Текст розпізнано автоматично (OCR): обов'язково перевірте вкладку «Контроль» і прев'ю."]
    if info.get("engine_kind") == "windows":
        notes.append(
            "Використано вбудований Windows OCR, який погано читає українські «і/ї/є»: для кращої якості "
            "встановіть рушій для української (кнопка в рядку OCR)."
        )
    return notes


def ocr_image(path, lang="uk", engine="auto"):
    """(таблиці, рядки_тексту, примітки) для файлу-зображення."""
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        words, info, fixed_note = recognize_best(img, lang, engine)
    tables = tables_from_image_words(words, "Фото/скан")
    inferred = infer_missing_quantities(tables)
    return tables, lines_from_words(words), notes_for(info) + [n for n in (fixed_note, inferred) if n]


def has_text_layer(path):
    """Чи є в PDF текстовий шар (інакше це скан: потрібен OCR)."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = pdf.pages[:3]
        return sum(len(p.chars) for p in pages) >= 20


def ocr_pdf(path, lang="uk", progress=None, engine="auto"):
    """(таблиці, рядки_тексту, примітки) для PDF-скану: кожна сторінка відтворюється як зображення."""
    import pdfplumber

    tables, lines, info = [], [], {}
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        images = []
        for number, page in enumerate(pdf.pages, 1):
            if progress:
                progress(number, total)
            images.append(page.to_image(resolution=DPI).original.convert("RGB"))
    if resolve_engine(engine) == "rapid":
        recognized = [(w, dict(i, engine_kind="rapid")) for w, i in ocr_rapid.recognize_many(images)]
    else:
        recognized = [recognize_image(img, lang, engine) for img in images]
    fixed_notes = []
    for number, (words, info) in enumerate(recognized, 1):
        words, fixed_note = correct_ukrainian(words)
        if resolve_engine(engine) == "rapid":  # сторінка без узгодженої таблиці - ще раз із вирівняним контрастом
            page_tables = tables_from_image_words(words, "x")
            quality = table_quality(page_tables)
            if quality < 1 and (quality > 0 or number == 1):
                words2, info2 = recognize_image(images[number - 1], lang, engine, contrast=True)
                words2, note2 = correct_ukrainian(words2)
                if table_stats(tables_from_image_words(words2, "x")) > table_stats(page_tables):
                    words, info, fixed_note = words2, info2, note2
        if fixed_note:
            fixed_notes.append(fixed_note)
        page_tables = tables_from_image_words(words, f"Стор. {number}")
        inferred = infer_missing_quantities(page_tables)
        if inferred:
            fixed_notes.append(inferred)
        tables += page_tables
        if number <= 2:
            lines += lines_from_words(words)
    return tables, lines, notes_for(info) + fixed_notes[:2]
