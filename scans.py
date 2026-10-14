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
    "name": ("найменування", "товари", "товар", "послуг", "послуги", "робіт", "назва", "опис"),
    "qty": ("кількість", "кіл-сть"),
    "price": ("ціна",),
    "sum": ("сума", "вартість"),
}
_TOTAL_LINE = re.compile(r"^\s*(разом|всього|усього|итого|всего|загальна\s+вартість|total)\b", re.IGNORECASE)
_UNIT_CELL = re.compile(r"^(?:\d{1,4}\s*)?[^\d\s.,]{1,6}\.?$")
_QTY_UNIT = re.compile(r"^(\d[\d\s.,]*?)\s+([^\d\s.,]\S{0,7})$")


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


_KNOWN_UNITS = ("шт", "кг", "г", "л", "мл", "м", "м2", "м3", "км", "см", "мм", "т", "год", "хв", "доба", "дн",
                "міс", "уп", "упак", "пач", "компл", "набір", "пар", "рул", "бут", "кор", "пак", "послуга", "послуг")


def fix_unit(unit):
    """Одиниця виміру після OCR: 'шT' -> 'шт', 'wт' -> 'шт', '1оо шт' -> '100 шт', 'род' -> 'год'."""
    unit = str(unit).strip().replace("w", "ш").replace("W", "Ш")
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
    """Кількість, яку OCR не прочитав (дрібний текст поруч із рамкою), обчислюється як сума ÷ ціна, якщо вийшло
    чисте число. Повертає примітку з номерами рядків або None."""
    rows_done = []
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
            if str(row[qty_i]).strip():
                continue
            price, total = checks.to_decimal(row[price_i]), checks.to_decimal(row[sum_i])
            if not price or total is None:
                continue
            qty = total / price
            if abs(qty - qty.to_integral_value()) <= checks.Decimal("0.0005") and qty > 0:
                row[qty_i] = str(int(qty.to_integral_value()))
                rows_done.append(number)
    if not rows_done:
        return None
    return "Кількість у рядках " + ", ".join(map(str, rows_done)) + " не розпізнано й обчислена як сума ÷ ціна — перевірте."


def table_quality(tables):
    """0..1: частка рядків обраної таблиці, де кількість, ціна й сума - числа і кількість × ціна = сума.
    1 - таблицю знайдено й вона узгоджена; 0 - таблиці або товарів немає."""
    table = next((t for t in tables if t.selected), None)
    if table is None:
        return 0.0
    prepared = converter.prepare_rows(table.rows, table.merges, flatten_newlines=True, trim_trailing_empty=True,
                                      sanitize_quotes=False, fill_merges=True, normalize_numbers=False)
    if len(prepared) < 2:
        return 0.0
    mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr")
    items, _ = profiles.extract_items(prepared, mapping)
    if not items:
        return 0.0
    good = 0
    for item in items:
        qty = checks.to_decimal(profiles.split_quantity(item.get("Количество", ""))[0])
        price, total = checks.to_decimal(item.get("Цена")), checks.to_decimal(item.get("Сумма"))
        if qty is None or price is None or total is None:
            continue
        diff = abs(qty * price - total)
        if diff <= checks.Decimal("0.02") or diff <= abs(total) * checks.Decimal("0.005"):
            good += 1
    return good / len(items)


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
    if quality >= 1 or (quality == 0 and not first_page):
        return words, info, note
    words2, info2 = recognize_image(img, lang, engine, contrast=True)
    words2, note2 = correct_ukrainian(words2)
    if table_quality(tables_from_image_words(words2, "x")) > quality:
        return words2, info2, note2
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


def _numeric_header(order):
    """Назви колонок: одна ціна/сума - 'Ціна', 'Сума'; дві - 'без ПДВ' і 'з ПДВ'; більше - з номером."""
    names = []
    for group, base in (("price", "Ціна"), ("sum", "Сума")):
        count = order.count(group)
        if count == 1:
            names.append(base)
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


def form_table_from_words(words, name):
    """Таблиця друкованої форми (акт, рахунок) за заголовком і вмістом: знаходить рядок шапки за ключовими
    словами (з допуском на помилки OCR; достатньо 'Найменування' + 'Сума'), потім рядки з числами до
    рядка 'Разом'. Працює й для таблиці з одним рядком і для кількох колонок цін/сум (без ПДВ / з ПДВ);
    назва товару на кілька рядків склеюється. Назви колонок канонічні."""
    lines = sources._line_cells_from_words(words)
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
        rows, name_x = [], None
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
        if rows:
            name_cell = next((c[2] for c in cells if _fuzzy_any(c[2], _FORM_WORDS["name"])), "Найменування")
            name_cell = fix_header_text(name_cell)
            header = ["№", name_cell, "Кількість", "Од."] + _numeric_header(out_groups)
            width = len(header)
            rows = [(r + [""] * width)[:width] for r in rows]
            for r in rows:
                r[3] = fix_unit(r[3])
            units = {r[3] for r in rows if r[3]}
            for r in rows:  # одиниця '100 шт', злита з назвою
                if not r[3]:
                    for u in units:
                        m = re.search(r"\s" + re.escape(u) + r"(?=\s|\(|$)", r[1])
                        if m:
                            r[3], r[1] = u, (r[1][: m.start()] + r[1][m.end():]).strip()
                            break
            return sources.Table(f"{name}, табл. 1 (за заголовком)", [header] + rows)
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
            quality = table_quality(tables_from_image_words(words, "x"))
            if quality < 1 and (quality > 0 or number == 1):
                words2, info2 = recognize_image(images[number - 1], lang, engine, contrast=True)
                words2, note2 = correct_ukrainian(words2)
                if table_quality(tables_from_image_words(words2, "x")) > quality:
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
