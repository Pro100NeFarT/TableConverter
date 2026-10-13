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
    "buyer": r"Покупець|Покупатель|Замовник|Заказчик|Платник|Плательщик|Одержувач|Получатель вантажу",
    "contract": r"Договір|Договор",
    "basis": r"Підстава|Основание",
    "warehouse": r"Склад",
    "division": r"Підрозділ|Подразделение",
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
_TITLE_RE = re.compile(
    r"^(?P<type>[^\n№]*?)[ \t]*№[ \t]*(?P<num>[^\s,;]+)(?:[ \t]+(?:(?:від|от)[ \t]+)?|[ \t]*\n[ \t]*(?:від|от)[ \t]+)"
    r"(?P<date>\d[^\n]*?)[ \t]*$",
    re.MULTILINE,
)
_NOT_A_TITLE = re.compile(r"^(?:договір|договор|підстава|основание)\b", re.IGNORECASE)
_NAME_SPLIT_RE = re.compile(
    r",\s*(?=(?:ІПН|ІНН|ЄДРПОУ|ЕДРПОУ|код\b|р/р|р/с|IBAN|ДРФО|тел\b|UA\d{2}|\d{5}\b))"
    r"|\s+(?=(?:п/р|р/р|р/с|IBAN|ЄДРПОУ|ЕДРПОУ|ІПН|ІНН|тел|Код\s+за|Адреса|[Юю]р\.\s*адрес\w*|Поточний\s+рахунок|Платник\s+податку|Загальна\s+система|Система\s+оподаткування)\b)",
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
_RECIPIENT_RE = re.compile(r"^[ \t]*(?:Отримувач|Получатель)\b", re.IGNORECASE | re.MULTILINE)
_SAME_AS_ABOVE = re.compile(r"^(?:той\s+(?:же|самий)|тот\s+же)\b", re.IGNORECASE)
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
    name = re.sub(r"[\s,]+\d{5,}[,.]?$", "", name)  # хвіст з іншого рядка (МФО тощо)
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


_MONEY_RE = re.compile(r"(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)[.,]\d{2}")


def _amounts(chunk):
    return _MONEY_RE.findall(chunk)


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
        if kind and len(kind) <= 60 and not _NOT_A_TITLE.match(kind):
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
        raw = head[m.end():end]
        if key in ("contract", "warehouse", "basis", "division"):
            raw = next((line for line in raw.split("\n") if line.strip()), "")
        value = _clean(raw)
        if key == "buyer" and _SAME_AS_ABOVE.match(value):
            continue  # 'Платник: той же'
        if key == "basis":
            if re.search(r"Договір|Договор", value, re.IGNORECASE) and "contract" not in segments:
                segments["contract"] = value  # 'Підстава: Договір № ... від ...'
            continue
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
                tax = _TAX_ID_RE.search(segments[key])
                if tax and code.startswith("ЄДРПОУ") and tax.group(1) != code.split()[-1]:
                    found.append((f"{title_ua}: ІПН", f"ІПН {tax.group(1)}"))
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
    total_re = re.compile(r"(?:^|\t)[ \t]*(?:Разом|Всього|Усього|Итого|Всего)[ \t]*:?[ \t]*" + _AMOUNTS_LINE, flags)
    totals_found = [m for m in total_re.finditer(text) if not re.match(r"[ \t]*(?:із|з|с)[ \t]+(?:ПДВ|НДС)", m.string[m.end(): m.end() + 8], re.I)]
    total = totals_found[0] if totals_found else None
    vat = re.search(
        r"(?:^|\t)[ \t]*(?:Сума\s+ПДВ|Сумма\s+НДС|У\s+тому\s+числі\s+ПДВ|ПДВ(?:\s+\d+\s*%)?|НДС(?:\s+\d+\s*%)?)[ \t]*:?[ \t]*"
        + _AMOUNTS_LINE,
        text,
        flags,
    )
    with_vat = re.search(
        r"^[ \t]*(?:Разом|Всього|Усього|Итого|Всего)[ \t]+(?:із|з|с)[ \t]+(?:ПДВ|НДС)[ \t]*:?[ \t]*" + _AMOUNTS_LINE,
        text,
        flags,
    )
    if total:
        sums = _amounts(total.group(1)) if "\t" not in total.group(1).strip() else []
        if len(sums) == 2 and not with_vat:
            # 'Разом: 384 768,60 461 722,32' - без ПДВ і з ПДВ в одному рядку
            found.append(("Разом", _clean(sums[0])))
            found.append(("Разом з ПДВ", _clean(sums[1])))
        else:
            found.append(("Разом", _last_amount(total.group(1))))
        if len(totals_found) > 1 and not with_vat:
            last = _last_amount(totals_found[-1].group(1))
            if last and last != _last_amount(total.group(1)):
                found.append(("Разом з ПДВ", last))
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
