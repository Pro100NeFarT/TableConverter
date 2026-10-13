"""
Реквізити друкованої форми (накладна, рахунок, акт): документ, номер, дата, сторони,
договір, склад, суми. Евристики для українських/російських форм; повертає лише знайдене.
"""
import os
import re

MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
    "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

_LABELS = {
    "supplier": r"Постачальник|Продавець|Поставщик|Продавец",
    "buyer": r"Покупець|Покупатель|Замовник|Заказчик|Платник|Плательщик",
    "contract": r"Договір|Договор",
    "warehouse": r"Склад",
    "delivery": r"Адреса\s+доставки|Адрес\s+доставки",
}
_LABEL_RE = re.compile(
    r"^[ \t]*(?:" + "|".join(f"(?P<{k}>{v})" for k, v in _LABELS.items()) + r")\b[ \t]*:?[ \t]*",
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_HEADER_RE = re.compile(r"^[ \t]*№[ \t]+\S.*(?:Товар|Назва|Найменування|Наименование|Кількість|Количество)", re.IGNORECASE | re.MULTILINE)
_TITLE_RE = re.compile(r"^(?P<type>[^\n№]*?)[ \t]*№[ \t]*(?P<num>[^\s,;]+)[ \t]+(?:від|от)[ \t]+(?P<date>[^\n]+?)[ \t]*$", re.MULTILINE)
_NAME_SPLIT_RE = re.compile(
    r",\s*(?=(?:ІПН|ІНН|ЄДРПОУ|ЕДРПОУ|код\b|р/р|р/с|IBAN|ДРФО|тел\b|UA\d{2}|\d{5}\b))", re.IGNORECASE
)
_TAX_ID_RE = re.compile(r"(?:ІПН|ІНН)\s*:?\s*(\d{8,12})", re.IGNORECASE)
_EDRPOU_RE = re.compile(r"(?:ЄДРПОУ|ЕДРПОУ)\s*:?\s*(\d{8,10})", re.IGNORECASE)
_IBAN_RE = re.compile(r"\bUA\d{27}\b")
_AMOUNT = r"(\d[\d   ]*[.,]\d{2})"


def parse_date(text):
    """'23 вересня 2026 р.' / '23.09.2026' -> '23.09.2026'; None, якщо не розпізнано."""
    m = re.search(r"(\d{1,2})\s+([А-Яа-яІіЇїЄєҐґ]+)\s+(\d{4})", text)
    if m and m.group(2).lower() in MONTHS:
        return f"{int(m.group(1)):02d}.{MONTHS[m.group(2).lower()]:02d}.{m.group(3)}"
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    return None


def _clean(text):
    return " ".join(text.split())


def _split_party(text):
    """'ФОП Іванов, ІПН 123, р/р UA..' -> (назва, код, IBAN)."""
    text = _clean(text)
    name = _NAME_SPLIT_RE.split(text, maxsplit=1)[0].strip(" ,")
    code = None
    m = _EDRPOU_RE.search(text)
    if m:
        code = f"ЄДРПОУ {m.group(1)}"
    else:
        m = _TAX_ID_RE.search(text)
        if m:
            code = f"ІПН {m.group(1)}"
    iban = _IBAN_RE.search(text)
    return name, code, iban.group(0) if iban else None


def parse_header_text(text, filename=""):
    """Повертає список (поле, значення) у зручному порядку; порожні значення не повертаються."""
    stop = _TABLE_HEADER_RE.search(text)
    head = text[: stop.start()] if stop else text
    found = []

    title = None
    for m in _TITLE_RE.finditer(head):
        kind = m.group("type").strip(" :")
        if kind and len(kind) <= 60 and not re.match(r"(?i)договір|договор", kind):
            title = (kind, m.group("num"), parse_date(m.group("date")) or _clean(m.group("date")))
            break
    if title:
        found += [("Документ", title[0]), ("Номер", title[1]), ("Дата", title[2])]

    name_match = re.search(r"№\s*([^\s]+)\s+(?:від|от)\s+(\d{1,2}[./]\d{1,2}[./]\d{4})", filename)
    if name_match:
        file_num, file_date = name_match.group(1), parse_date(name_match.group(2))
        if not title:
            found += [("Номер (з назви файлу)", file_num), ("Дата (з назви файлу)", file_date)]
        else:
            if file_num != title[1]:
                found.append(("Номер у назві файлу", file_num))
            if file_date and file_date != title[2]:
                found.append(("Дата у назві файлу", file_date))

    segments = {}
    labels = list(_LABEL_RE.finditer(head))
    for i, m in enumerate(labels):
        key = m.lastgroup
        end = labels[i + 1].start() if i + 1 < len(labels) else len(head)
        value = _clean(head[m.end():end])
        if value and key not in segments:
            segments[key] = value

    for key, title_ua in (("supplier", "Постачальник"), ("buyer", "Покупець")):
        if key in segments:
            name, code, iban = _split_party(segments[key])
            found.append((title_ua, name))
            if code:
                found.append((f"{title_ua}: код", code))
            if iban:
                found.append((f"{title_ua}: IBAN", iban))
    for key, label in (("contract", "Договір"), ("warehouse", "Склад"), ("delivery", "Адреса доставки")):
        if key in segments:
            found.append((label, segments[key]))

    count = re.search(
        r"(?:Всього|Всего)\s+(?:найменувань|наименований)\s+(\d+)(?:\s*,\s*на\s+(?:суму|сумму)\s+" + _AMOUNT + ")?",
        text,
        re.IGNORECASE,
    )
    if count:
        found.append(("Кількість найменувань", count.group(1)))
    total = re.search(r"^[ \t]*Разом\s*:?\s*" + _AMOUNT, text, re.IGNORECASE | re.MULTILINE)
    if total:
        found.append(("Разом", _clean(total.group(1))))
    elif count and count.group(2):
        found.append(("Разом", _clean(count.group(2))))
    return found


def extract_pdf_info(path):
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            return []
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    return parse_header_text(text, os.path.basename(path))
