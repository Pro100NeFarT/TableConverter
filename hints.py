"""
Підказки операторові: що вводити в налаштуваннях 1С-обробок (роздільник, перший/останній рядок
з товаром, підвал, номери колонок) для щойно збереженого файлу.
"""
import profiles


def csv_lines(profile_key, delimiter):
    profile = profiles.PROFILES[profile_key]
    shown = "Tab" if delimiter == "\t" else delimiter
    lines = [
        f"Обробка: {profile['title']}",
        "",
        f"Роздільник csv (поле на вкладці «Настройка»): {shown}",
        "Рядок заголовка: 1 (обробка читає його сама)",
        "Колонки: натисніть «Колонки по умолчанию» - порядок у файлі збігається з ними.",
        "",
        "Порядок колонок у файлі:",
    ]
    lines += [f"  {n}. {name}" for n, name in enumerate(profile["fields"], 1)]
    return lines


def column_numbers(prepared_header, mapping):
    """{поле: індекс колонки таблиці з нуля} для підібраних полів."""
    result = {}
    for field, header in mapping.items():
        idx = profiles.column_index(prepared_header, header)
        if idx is not None:
            result[field] = idx
    return result


def _trailing_totals(rows, name_idx):
    count = 0
    for row in reversed(rows[1:]):
        if all(not str(c).strip() for c in row) or profiles.is_total_row(row, name_idx):
            count += 1
        else:
            break
    return count


def _columns_text(numbers, col_of=None):
    pairs = []
    for field, idx in numbers.items():
        col = idx if col_of is None else col_of.get(idx)
        if col is not None:
            pairs.append((col, field))
    return "; ".join(f"{field} = {col + 1}" for col, field in sorted(pairs))


def excel_lines_table_only(entries):
    """entries: [(назва_аркуша, рядки_таблиці, заголовок_після_підбору, mapping)] у порядку аркушів."""
    lines = ["Excel: лише таблиця (аркуші в порядку збереження)", ""]
    for n, (name, rows, header, mapping) in enumerate(entries, 1):
        numbers = column_numbers(header, mapping)
        tail = _trailing_totals(rows, numbers.get("Наименование"))
        last = len(rows) - tail
        lines += [
            f"Аркуш «{name}»:",
            f"  НомерЛиста = {n}",
            f"  ПерваяСтрокаСТоваром = 2",
            f"  ПоследняяСтрокаСТоваром = {last}   (або КоличествоСтрокПодвала = {tail})",
            f"  Колонки: {_columns_text(numbers)}",
            "",
        ]
    return lines


def excel_lines_layout(layout_sheets, entries):
    """entries: [(таблиця, заголовок_після_підбору, mapping)]; layout_sheets - аркуші 'один в один'."""
    lines = ["Excel 1 в 1 (кожна сторінка PDF - окремий аркуш)", ""]
    found = False
    for n, sheet in enumerate(layout_sheets, 1):
        for meta in sheet.meta:
            for table, header, mapping in entries:
                if [c.lower() for c in table.rows[0]] != [c.lower() for c in meta["header"]]:
                    continue
                found = True
                numbers = column_numbers(header, mapping)
                tail = _trailing_totals(table.rows, numbers.get("Наименование"))
                first = meta["header_row"] + 2
                last = meta["last_row"] + 1 - tail
                lines += [
                    f"Аркуш «{sheet.name}»:",
                    f"  НомерЛиста = {n}",
                    f"  ПерваяСтрокаСТоваром = {first}",
                    f"  ПоследняяСтрокаСТоваром = {last}   (або КоличествоСтрокПодвала = {sheet.n_rows - last})",
                    f"  Колонки: {_columns_text(numbers, meta['col_map'])}",
                    "",
                ]
    if not found:
        lines.append("Не вдалося співставити обрану таблицю з аркушами - налаштуйте рядки й колонки вручну.")
    return lines


def json_lines(document):
    """Підказка для обробки УпрИмпортИзExcel: що буде заповнено з JSON і що перевірити вручну."""
    header = document.get("Шапка", {})
    lines = [
        "Обробка: УпрИмпортИзExcel (керовані форми)",
        "",
        "Як завантажити: у полі «Файл» оберіть цей .json і натисніть «Загрузить».",
        "Шапка й таблиця заповняться з файлу; пошук номенклатури працює як зазвичай.",
        "Налаштування колонок, роздільника й рядків для JSON не потрібні.",
        "",
        "Що буде заповнено в шапці:",
    ]
    seller, contract = header.get("Поставщик"), header.get("Договор")
    lines.append(f"  Номер вхідного: {header.get('Номер') or '— не знайдено —'}")
    lines.append(f"  Дата вхідного: {header.get('ДатаТекст') or '— не знайдено —'}")
    lines.append(
        "  Контрагент: "
        + (f"{seller.get('Наименование', '')} (ЄДРПОУ {seller['ЕДРПОУ']})" if seller and seller.get("ЕДРПОУ")
           else f"{seller.get('Наименование', '')} (ІПН {seller['ИНН']})" if seller and seller.get("ИНН")
           else (seller or {}).get("Наименование") or "— не знайдено —")
    )
    lines.append(f"  Договір: {contract.get('Представление') if contract else '— не знайдено —'}")
    lines.append(f"Позицій у таблиці: {len(document.get('Товары', []))}")
    problems = [m["Сообщение"] for m in document.get("Контроль", []) if m["Уровень"] != "ok"]
    if problems:
        lines += ["", "Зверніть увагу (вкладка «Контроль»):"] + [f"  - {text}" for text in problems]
    return lines
