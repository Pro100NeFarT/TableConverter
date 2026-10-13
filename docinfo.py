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
    "supplier": r"Постачальник|Продавець|Виконавець|Поставщик|Продавец|Исполнитель",
    "buyer": r"Покупець|Покупатель|Замовник|Заказчик|Платник|Плательщик",
    "contract": r"Договір|Договор",
    "warehouse": r"Склад",
    "delivery": r"Адреса\s+доставки|Адрес\s+доставки",
}
_LABEL_RE = re.compile(
    r"^[ \t]*(?:" + "|".join(f"(?P<{k}>{v})" for k, v in _LABELS.items()) + r")\b[ \t]*:?[ \t]*",
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_HEADER_RE = re.compile(
    r"^[^\n]*?(?:Товар|Назва|Найменування|Наименование)[^\n]*?(?:Кількість|Количество|Кіл-сть|К-сть)[^\n]*?(?:Ціна|Цена|Сума|Сумма)[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
_TITLE_RE = re.compile(r"^(?P<type>[^\n№]*?)[ \t]*№[ \t]*(?P<num>[^\s,;]+)[ \t]+(?:(?:від|от)[ \t]+)?(?P<date>\d[^\n]*?)[ \t]*$", re.MULTILINE)
_NAME_SPLIT_RE = re.compile(
    r",\s*(?=(?:ІПН|ІНН|ЄДРПОУ|ЕДРПОУ|код\b|р/р|р/с|IBAN|ДРФО|тел\b|UA\d{2}|\d{5}\b))"
    r"|\s+(?=(?:п/р|р/р|р/с|IBAN|ЄДРПОУ|ЕДРПОУ|ІПН|ІНН|тел)\b)",
    re.IGNORECASE,
)
_TAX_ID_RE = re.compile(r"(?:ІПН|ІНН)\s*:?\s*(\d{8,12})", re.IGNORECASE)
_EDRPOU_RE = re.compile(r"(?:ЄДРПОУ|ЕДРПОУ)\s*:?\s*(\d{8,10})", re.IGNORECASE)
_IBAN_RE = re.compile(r"\bUA\d{27}\b")
_ORG_START = re.compile(
    r"^(?:ТОВ|ТзОВ|ТДВ|ПП|ФОП|ПАТ|АТ|ПрАТ|ДП|КП|ФО|ООО|ИП|Фізична|Товариство|Приватне|Публічне|Акціонерне|Державне|Підприємець)\b",
    re.IGNORECASE,
)
_AMOUNTS_LINE = r"((?:\d[\d   ]*[.,]\d{2}[ \t]*)+)"
_RECIPIENT_RE = re.compile(r"^[ \t]*(?:Отримувач|Одержувач|Получатель)\b", re.IGNORECASE | re.MULTILINE)
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


def _last_amount(chunk):
    """Права сума в рядку підсумків (комірки розділені табуляцією; у друкованих формах - сума без ПДВ)."""
    parts = [p for p in re.split(r"\t+", chunk.strip()) if p.strip()]
    return _clean(parts[-1]) if parts else ""


def _recipient_code(text):
    """Код отримувача з блоку платіжного доручення: 'Код 12345678' або 'Код' з цифрами в наступних рядках."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not _RECIPIENT_RE.match(line):
            continue
        window = lines[i: i + 8]
        for j, candidate in enumerate(window):
            m = re.match(r"^\s*Код\b[ \t]*:?[ \t]*(\d{8,10})\b", candidate, re.IGNORECASE)
            if m:
                return m.group(1)
            if re.match(r"^\s*Код\b", candidate, re.IGNORECASE):
                for nxt in window[j + 1: j + 4]:
                    if re.fullmatch(r"\s*\d{8,10}\s*", nxt):
                        return nxt.strip()
    return None


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
        if key in ("supplier", "buyer") and ":" not in m.group(0) and not _ORG_START.match(value):
            continue  # слово з тексту речення (напр. "Замовник претензій не має"), а не підпис сторони
        if value and key not in segments:
            segments[key] = value

    for key, title_ua in (("supplier", "Постачальник"), ("buyer", "Покупець")):
        if key in segments:
            name, code, iban = _split_party(segments[key])
            if key == "supplier" and not code:
                digits = _recipient_code(head)
                if digits:
                    code = f"ЄДРПОУ {digits}" if len(digits) == 8 else f"ІПН {digits}"
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
    flags = re.IGNORECASE | re.MULTILINE
    total = re.search(r"^[ \t]*(?:Разом|Всього|Усього|Итого|Всего)[ \t]*:?[ \t]*" + _AMOUNTS_LINE, text, flags)
    vat = re.search(r"^[ \t]*(?:Сума\s+ПДВ|Сумма\s+НДС)[ \t]*:?[ \t]*" + _AMOUNTS_LINE, text, flags)
    with_vat = re.search(
        r"^[ \t]*(?:Разом|Всього|Усього|Итого|Всего)[ \t]+(?:із|з|с)[ \t]+(?:ПДВ|НДС)[ \t]*:?[ \t]*" + _AMOUNTS_LINE,
        text,
        flags,
    )
    if total:
        found.append(("Разом", _last_amount(total.group(1))))
    elif count and count.group(2):
        found.append(("Разом", _clean(count.group(2))))
    if vat:
        found.append(("ПДВ", _last_amount(vat.group(1))))
    if with_vat:
        found.append(("Разом з ПДВ", _last_amount(with_vat.group(1))))

    if not any(label.endswith(": код") for label, _ in found):
        # сторони не підписані (акт, скан): збираємо всі коди й рахунки з тексту, щоб оператор міг їх скопіювати
        ids = []
        for m in re.finditer(r"(?:ЄДРПОУ|ЕДРПОУ)\s*:?\s*(\d{8,10})", text, re.IGNORECASE):
            ids.append(f"ЄДРПОУ {m.group(1)}")
        for m in re.finditer(r"(?:ІПН|ІНН|ДРФО)\s*:?\s*(\d{10,12})", text, re.IGNORECASE):
            ids.append(f"ІПН {m.group(1)}")
        ibans = _IBAN_RE.findall(text)
        if ids:
            found.append(("Коди в тексті", "; ".join(dict.fromkeys(ids))))
        if ibans:
            found.append(("IBAN у тексті", "; ".join(dict.fromkeys(ibans))))
    return found


def extract_pdf_info(path):
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            return []
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    return parse_header_text(text, os.path.basename(path))
