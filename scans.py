"""
Скани й фото: розпізнавання тексту (OCR) -> слова з координатами -> таблиці й реквізити
тим самим розбором, що й для PDF без ліній. Движок - вбудований Windows OCR (ocr_windows).
Результат OCR завжди треба перевіряти: вкладка «Контроль» ловить помилки цифр.
"""
import difflib
import os
import re

import ocr_rapid
import ocr_windows
import sources

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


def fix_rows(rows):
    return [[fix_numeric_cell(c) for c in row] for row in rows]


def resolve_engine(engine="auto"):
    """'auto': рушій для української (RapidOCR), якщо встановлений, інакше вбудований Windows OCR."""
    if engine == "auto":
        return "rapid" if ocr_rapid.is_installed() else "windows"
    return engine


def recognize_image(img, lang="uk", engine="auto"):
    """Слова зображення з виправленням нахилу. Повертає (слова, інфо); інфо['engine'] - 'rapid' або 'windows'.
    Windows OCR: якщо бачить кут тексту, зображення вирівнюється й розпізнається вдруге; RapidOCR вирівнює сам."""
    from PIL import Image

    if resolve_engine(engine) == "rapid":
        words, info = ocr_rapid.recognize(img)
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


def lines_from_words(words):
    """Текст сторінки по рядках для зчитування реквізитів (комірки розділені табуляцією)."""
    return ["\t".join(cell[2] for cell in cells) for _, cells in sources._line_cells_from_words(words)]


def _fuzzy_any(text, words, threshold=0.72):
    tokens = re.findall(r"[а-яіїєґ'a-z0-9-]{3,}", text.lower())
    return any(difflib.SequenceMatcher(None, t, w).ratio() >= threshold for t in tokens for w in words)


def _is_number(text):
    return bool(_NUMBER.match(text.replace("\u00a0", " ").strip()))


def _parse_form_row(cells, expected):
    """Рядок таблиці-форми за вмістом: [№, назва, кількість, одиниця, ціна, сума] або None (немає чисел)."""
    items = []  # (x0, 'num'|'text', значення)
    for x0, _x1, text in cells:
        fixed = str(fix_numeric_cell(text)).strip()
        m = _QTY_UNIT.match(fixed)
        if m and _is_number(m.group(1)):
            items.append((x0, "num", m.group(1).strip()))
            items.append((x0 + 1, "text", m.group(2)))
        elif _is_number(fixed):
            items.append((x0, "num", fixed))
        else:
            items.append((x0, "text", text.strip()))
    index = ""
    if len(items) >= 3 and items[0][1] == "num" and re.fullmatch(r"\d{1,3}", items[0][2]):
        index = items.pop(0)[2]
    numbers = [i for i in items if i[1] == "num"]
    if not numbers:
        return None
    count = min(len(numbers), 3)
    targets = expected if len(expected) == len(numbers) else ("qty", "price", "sum")[-count:] if count > 2 else ("price", "sum")[-count:]
    values = {g: n[2] for g, n in zip(targets, numbers[-len(targets):])}
    texts = [i for i in items if i[1] == "text"]
    unit = ""
    for t in texts[1:]:
        if len(t[2]) <= 8 and not any(ch.isdigit() for ch in t[2]) and t[0] > numbers[0][0]:
            unit = t[2]
            break
    name = " ".join(t[2] for t in texts if t[2] != unit or t is texts[0])
    return [index, name.strip(), values.get("qty", ""), unit, values.get("price", ""), values.get("sum", "")]


def form_table_from_words(words, name):
    """Таблиця друкованої форми (акт, рахунок) за заголовком і вмістом: знаходить рядок шапки за ключовими
    словами (з допуском на помилки OCR; достатньо 'Найменування' + 'Сума'), потім рядки з числами до
    рядка 'Разом'. Працює й для таблиці з одним рядком. Назви колонок канонічні."""
    lines = sources._line_cells_from_words(words)
    for h, (_top, cells) in enumerate(lines):
        groups = {g for g, ws in _FORM_WORDS.items() if any(_fuzzy_any(c[2], ws) for c in cells)}
        if len(cells) < 2 or "name" not in groups or not groups & {"qty", "price", "sum"}:
            continue
        expected = tuple(g for g in ("qty", "price", "sum") if g in groups)
        rows, name_x = [], None
        for _t, row_cells in lines[h + 1:]:
            if _TOTAL_LINE.match(" ".join(c[2] for c in row_cells)):
                break
            parsed = _parse_form_row(row_cells, expected)
            if parsed:
                rows.append(parsed)
                name_x = min(c[0] for c in row_cells[1:] or row_cells)
                continue
            if rows and len(row_cells) == 1 and name_x is not None and abs(row_cells[0][0] - name_x) <= 80:
                rows[-1][1] = f"{rows[-1][1]} {row_cells[0][2]}".strip()
                continue
            if rows:
                break
        if rows:
            name_cell = next((c[2] for c in cells if _fuzzy_any(c[2], _FORM_WORDS["name"])), "Найменування")
            name_cell = fix_header_text(name_cell)
            header = ["№", name_cell, "Кількість", "Од.", "Ціна", "Сума"]
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
        words, info = recognize_image(img, lang, engine)
    tables = tables_from_image_words(words, "Фото/скан")
    return tables, lines_from_words(words), notes_for(info)


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
    for number, (words, info) in enumerate(recognized, 1):
        tables += tables_from_image_words(words, f"Стор. {number}")
        if number <= 2:
            lines += lines_from_words(words)
    return tables, lines, notes_for(info)
