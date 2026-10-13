"""Автотест друкованих форм в Excel (.xlsx і .xls): таблиця всередині аркуша, об'єднана шапка,
реквізити, підсумки з ПДВ, вибір ціни/суми у формі зі знижкою. Файли синтетичні (xlwt - лише для тестів)."""
import os
import tempfile

import openpyxl
import xlwt

os.environ["TC_CONFIG_DIR"] = tempfile.mkdtemp()

import checks
import converter
import docinfo
import profiles
import sources

IBAN = "UA" + "1" * 27
TITLE = "Рахунок на оплату № ТЕ-0000123 від 5 жовтня 2026 р."
RECIPIENT = 'Отримувач     Товариство з обмеженою відповідальністю"Тест"\nКод\nБанк'
SUPPLIER = 'Постачальник:     Товариство з обмеженою відповідальністю"Тест"\nп/р ' + IBAN + ", Банк ПАТ Тест"
FOOTER = "Всього:    {a}\nСума ПДВ:     {v}\nВсього із ПДВ:  {t}"

ITEMS = [  # артикул, назва, кількість, одиниця, ціна, сума (з урахуванням знижки 40%)
    (1978, "Перехід розбірний 63*2", 388, "шт", 513.0),
    (1738, "Труба PN16  25x3,5", 600, "м", 18.0),
    (2411, "Труба pp-r 25 мм (80)", 1000, "м", 28.5),
]


def write_xlsx(path, discount):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Увага! Оплата цього рахунку означає погодження з умовами поставки товару."
    ws["A3"] = RECIPIENT
    ws["A4"] = "12345678"
    ws["A5"] = IBAN
    ws["A6"] = TITLE
    ws["A7"] = SUPPLIER
    ws["A8"] = "Договір:               К020525/657 от 02.05.25 UAH"
    ws["A10"], ws["B10"] = "№", "Артикул"
    ws["C10"] = "Товари (роботи, послуги)"
    ws.merge_cells("C10:E10")
    ws["F10"], ws["G10"] = "УКТ ВЕД", "Імпорт"
    ws["H10"] = "Кіл-сть"
    ws.merge_cells("H10:I10")
    first = 11
    if not discount:
        ws["J10"] = "Ціна без\nПДВ"
        ws.merge_cells("J10:K10")
        ws["L10"] = "Сума без\nПДВ"
    else:
        for col, text in (("J", "Ціна без ПДВ"), ("L", "Сума без знижки"), ("M", "Знижка"),
                          ("N", "Ціна зі знижкою без ПДВ"), ("O", "Сума без ПДВ")):
            ws[f"{col}10"] = text
    total = 0.0
    for i, (art, name, qty, unit, price) in enumerate(ITEMS):
        r = first + i
        ws[f"A{r}"], ws[f"B{r}"], ws[f"C{r}"] = i + 1, art, name
        ws.merge_cells(f"C{r}:E{r}")
        ws[f"H{r}"], ws[f"I{r}"] = qty, unit
        if not discount:
            ws[f"J{r}"], ws[f"L{r}"] = price, qty * price
            ws.merge_cells(f"J{r}:K{r}")
            total += qty * price
        else:
            eff = round(price * 0.6, 2)
            ws[f"J{r}"], ws[f"L{r}"] = price, qty * price
            ws[f"M{r}"], ws[f"N{r}"], ws[f"O{r}"] = round(qty * price * 0.4, 2), eff, round(qty * eff, 2)
            total += round(qty * eff, 2)
    last = first + len(ITEMS)
    vat = round(total * 0.2, 2)
    ws[f"A{last}"] = FOOTER.format(a=f"{total:,.2f}".replace(",", " ").replace(".", ","),
                                   v=f"{vat:,.2f}".replace(",", " ").replace(".", ","),
                                   t=f"{total + vat:,.2f}".replace(",", " ").replace(".", ","))
    ws[f"A{last + 1}"] = f"Всього найменувань {len(ITEMS)}, на суму {total + vat:,.2f} грн.".replace(",", " ", 1)
    wb.save(path)
    return total, vat


def write_xls(path, discount):
    wb = xlwt.Workbook()
    ws = wb.add_sheet("TDSheet")
    ws.write(0, 0, "Увага! Оплата цього рахунку означає погодження з умовами поставки товару.")
    ws.write(2, 0, RECIPIENT)
    ws.write(3, 0, "12345678")
    ws.write(4, 0, IBAN)
    ws.write(5, 0, TITLE)
    ws.write(6, 0, SUPPLIER)
    ws.write(7, 0, "Договір:               К020525/657 от 02.05.25 UAH")
    ws.write(9, 0, "№")
    ws.write(9, 1, "Артикул")
    ws.write_merge(9, 9, 2, 4, "Товари (роботи, послуги)")
    ws.write(9, 5, "УКТ ВЕД")
    ws.write(9, 6, "Імпорт")
    ws.write_merge(9, 9, 7, 8, "Кіл-сть")
    if not discount:
        ws.write_merge(9, 9, 9, 10, "Ціна без\nПДВ")
        ws.write(9, 11, "Сума без\nПДВ")
    else:
        for col, text in ((9, "Ціна без ПДВ"), (11, "Сума без знижки"), (12, "Знижка"),
                          (13, "Ціна зі знижкою без ПДВ"), (14, "Сума без ПДВ")):
            ws.write(9, col, text)
    total = 0.0
    for i, (art, name, qty, unit, price) in enumerate(ITEMS):
        r = 10 + i
        ws.write(r, 0, i + 1)
        ws.write(r, 1, art)
        ws.write_merge(r, r, 2, 4, name)
        ws.write(r, 7, qty)
        ws.write(r, 8, unit)
        if not discount:
            ws.write_merge(r, r, 9, 10, price)
            ws.write(r, 11, qty * price)
            total += qty * price
        else:
            eff = round(price * 0.6, 2)
            ws.write(r, 9, price)
            ws.write(r, 11, qty * price)
            ws.write(r, 12, round(qty * price * 0.4, 2))
            ws.write(r, 13, eff)
            ws.write(r, 14, round(qty * eff, 2))
            total += round(qty * eff, 2)
    last = 10 + len(ITEMS)
    ws.write(last + 1, 20, "Разом:")
    ws.write(last + 1, 22, total)
    ws.write(last + 2, 20, "Сума ПДВ:")
    ws.write(last + 2, 22, round(total * 0.2, 2))
    ws.write(last + 3, 20, "Усього з ПДВ:")
    ws.write(last + 3, 22, round(total * 1.2, 2))
    ws.write(last + 5, 0, f"Всього найменувань {len(ITEMS)}, на суму {total * 1.2:,.2f} грн.".replace(",", " ", 1))
    wb.save(path)
    return total, round(total * 0.2, 2)


tmp = tempfile.mkdtemp()
for ext, writer in ((".xlsx", write_xlsx), (".xls", write_xls)):
    for discount in (False, True):
        path = os.path.join(tmp, f"form_{int(discount)}{ext}")
        total, vat = writer(path, discount)
        tables = sources.load_excel_tables(path)
        assert [t.selected for t in tables] == [True, False], (ext, [(t.name, t.selected) for t in tables])
        t = tables[0]
        assert t.name.endswith(": таблиця") and t.n_rows == 1 + len(ITEMS), (ext, t.n_rows)
        header = t.rows[0]
        qty_i = header.index("Кіл-сть")
        assert header[qty_i + 1] == "" and (0, qty_i, 0, qty_i + 1) in t.merges, (ext, header, t.merges)
        assert t.rows[1][:2] == [1, 1978] and t.rows[1][qty_i] == 388 and t.rows[1][qty_i + 1] == "шт", t.rows[1]
        assert isinstance(t.rows[1][1], int), "артикул-число має бути цілим, без .0"

        info = dict(docinfo.parse_header_text("\n".join(t.lines), os.path.basename(path)))
        assert info["Документ"] == "Рахунок на оплату" and info["Номер"] == "ТЕ-0000123" and info["Дата"] == "05.10.2026", info
        assert info["Постачальник"].startswith("Товариство з обмеженою відповідальністю") and "п/р" not in info["Постачальник"], info
        assert info["Постачальник: код"] == "ЄДРПОУ 12345678" and info["Постачальник: IBAN"] == IBAN, info
        assert info["Договір"].startswith("К020525/657"), info
        assert info["Кількість найменувань"] == str(len(ITEMS)), info
        fmt = lambda x: f"{x:,.2f}".replace(",", " ").replace(".", ",")
        assert info["Разом"] == fmt(total) and info["ПДВ"] == fmt(vat), (info, total)
        assert info["Разом з ПДВ"] == fmt(round(total * 1.2, 2)), info

        prepared = converter.prepare_rows(t.rows, t.merges, fill_merges=True)
        assert prepared[0][qty_i + 1] == "Кіл-сть_2", prepared[0]
        mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr", "")
        assert mapping["Количество"] == "Кіл-сть" and mapping["Единица"] == "Кіл-сть_2" and mapping["УКТВЭД"] == "УКТ ВЕД", mapping
        if discount:
            assert mapping["Цена"] == "Ціна зі знижкою без ПДВ" and mapping["Сумма"] == "Сума без ПДВ", mapping
        else:
            assert mapping["Цена"] == "Ціна без ПДВ" and mapping["Сумма"] == "Сума без ПДВ", mapping
        res = checks.run_checks(prepared, mapping, info)
        assert not [m for lvl, m in res if lvl != "ok"], (ext, discount, res)
        rows = profiles.apply_profile(prepared, "upr", mapping)
        f = {name: i for i, name in enumerate(rows[0])}
        assert rows[1][f["Артикул"]] == "1978" and rows[1][f["Количество"]] == "388" and rows[1][f["Единица"]] == "шт"
        print(ext, "знижка" if discount else "без знижки", "- ок:", rows[1][f["Цена"]], rows[1][f["Сумма"]])

# звичайний аркуш без друкованої форми поводиться як раніше
plain = os.path.join(tmp, "plain.xlsx")
wb = openpyxl.Workbook()
wb.active.append(["КОД", "Назва", "Склад"])
wb.active.append(["1", "Мило", "Вода"])
wb.save(plain)
tables = sources.load_excel_tables(plain)
assert len(tables) == 1 and tables[0].lines == [] and tables[0].selected and tables[0].n_rows == 2
print("ВСІ ПЕРЕВІРКИ ФОРМ EXCEL ПРОЙДЕНО")
