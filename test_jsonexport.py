"""Автотест JSON-виходу: шапка з реквізитів, рядки товарів, типи значень, контроль, GUI-потік."""
import json
import os
import tempfile

import openpyxl

import converter
import docinfo
import jsonexport
import profiles
from app import App

# ---- шапка з тексту документа
TEXT = """Видаткова накладна № НФ-277 від 23 вересня 2026 р.
Постачальник: ТОВ "Ромашка", ЄДРПОУ 12345678, р/р UA213223130000026007233566001
Покупець: ФОП Іванов І. І., ІПН 1234567890
Договір: № 64 від 01.03.2023
Склад: Основний
Товар Кількість Ціна Сума
"""
pairs = docinfo.parse_header_text(TEXT)
header = jsonexport.build_header(pairs + [("Разом", "2 255,00"), ("Кількість найменувань", "1")])
assert header["Номер"] == "НФ-277" and header["Дата"] == "2026-09-23T00:00:00", header
assert header["Поставщик"]["ЕДРПОУ"] == "12345678" and header["Поставщик"]["IBAN"].startswith("UA21")
assert header["Покупатель"]["ИНН"] == "1234567890"
assert header["Договор"] == {"Представление": "№ 64 від 01.03.2023", "Номер": "64", "Дата": "2023-03-01T00:00:00"}, header["Договор"]
assert header["Итоги"] == {"Сумма": 2255, "КоличествоПозиций": 1}, header["Итоги"]
assert jsonexport.parse_contract("Договір №А-5 від 01.03.23")["Дата"] == "2023-03-01T00:00:00"
assert jsonexport.parse_contract("") is None

# ---- рядки товарів: числа, одиниця з кількості, нумерація
prepared = [
    ["№", "Артикул", "Назва", "Кількість", "Ціна", "Сума"],
    ["1", "A-1", 'Мило "Ерл грей"', "2 шт", "10,50", "21,00"],
    ["2", "", "Крем", "1,5", "100", "150,00"],
    ["", "", "Разом", "", "", "171,00"],
]
mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr")
items = jsonexport.build_items(prepared, mapping)
assert len(items) == 2, items
assert items[0]["Наименование"] == 'Мило "Ерл грей"'  # лапки не чіпаємо
assert items[0]["Количество"] == 2 and items[0]["Единица"] == "шт"
assert items[0]["Цена"] == 10.5 and items[0]["Сумма"] == 21
assert items[1]["Количество"] == 1.5 and "Артикул" not in items[1] and items[1]["НомерСтроки"] == 2

# ---- документ: контроль і серіалізація
doc = jsonexport.build_document(pairs, [(prepared, mapping, "Товари")], {"Файл": "x.xlsx", "Тип": "excel"})
assert doc["Формат"] == "TableConverter" and doc["ВерсияФормата"] == 1
assert any(m["Уровень"] == "ok" for m in doc["Контроль"])
text = json.dumps(doc, ensure_ascii=False)
assert json.loads(text)["Шапка"]["Номер"] == "НФ-277"

# ---- рамка форми в PDF: заголовок документа над шапкою й об'єднаний підсумок під таблицею
import sources
frame = [
    ["Накладна № 1 від 01.01.2026 Постачальник: ТОВ", "", "", "", ""],
    ["№", "Товар", "Кількість", "Ціна без ПДВ", "Сума без ПДВ"],
    ["1", "Мило", "2", "10,00", "20,00"],
    ["Разом: 20,00 24,00", "", "", "", ""],
]
rows, merges = sources.trim_form_frame(frame, [(0, 0, 0, 4), (3, 0, 3, 4)])
assert rows[0][1] == "Товар" and len(rows) == 2 and merges == [], (rows, merges)

# ---- Excel: кожен товар у два рядки (ціна/сума без ПДВ і під нею з ПДВ)
SRC2 = os.path.join(tempfile.gettempdir(), "tc_test_two_rows.xlsx")
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["Рахунок на оплату № 77 від 06 жовтня 2026"])
ws.append(["Підстава:", "Договір № ДФ-5 від 01.01.2026"])
ws.append(["№ п/п", "Код товару", "Найменування", "Од.", "Ціна без / з ПДВ", "Кількість", "Сума без / з ПДВ"])
ws.append([1, 3001001, "Емаль", "шт", 100.0, 3, 300.0])
ws.append([None, None, None, None, 120.0, None, 360.0])
ws.append([2, 3001002, "Грунт", "шт", 50.0, 2, 100.0])
ws.append([None, None, None, None, 60.0, None, 120.0])
ws.append(["Разом:", None, None, None, None, None, 400.0])
wb.save(SRC2)
table = sources.load_excel_tables(SRC2)[0]
os.remove(SRC2)
assert table.n_rows == 3, table.rows
assert table.rows[0][4] == "Ціна без ПДВ" and table.rows[0][5] == "Ціна з ПДВ", table.rows[0]
prep = converter.prepare_rows(table.rows, table.merges, flatten_newlines=True, trim_trailing_empty=True,
                              sanitize_quotes=False, fill_merges=True, normalize_numbers=False)
mp = profiles.resolve_mapping(prep[0], prep[1:], "upr")
goods = jsonexport.build_items(prep, mp)
assert [(g["Цена"], g["Сумма"]) for g in goods] == [(100, 300), (50, 100)], goods
assert jsonexport.parse_contract("Договір № ДФ-5 від 01.01.2026")["Номер"] == "ДФ-5"
sums = dict(docinfo.parse_header_text("Рахунок № 1 від 01.01.2026\nВсього кількість 5\tРазом:\t360 805,65\nПДВ 20%:\t72 161,13\nВСЬОГО:\t432 966,78\n"))
assert (sums["Разом"], sums["ПДВ"], sums["Разом з ПДВ"]) == ("360 805,65", "72 161,13", "432 966,78"), sums
both = dict(docinfo.parse_header_text("Накладна № 1 від 01.01.2026\nРазом: 384 768,60 461 722,32\n"))
assert (both["Разом"], both["Разом з ПДВ"]) == ("384 768,60", "461 722,32"), both

# ---- фото: Одержувач - покупець, 'Платник: той же', підстава не договір, заголовок у два рядки
photo = dict(docinfo.parse_header_text("Постачальник:\tТОВ \"Ромашка\" 325365,\nОдержувач:\tФОП Іванов І. І.\nКод за ЄДРПОУ 1234567890. Україна, 21030, м. Вінниця\nПлатник:\tтой же\nПідстава:\tРахунок на оплату № ВД-6841 від 12.10.2026\nДоговір:\t№ ВД 22-12-2022/1 від 22.12.2022\nВидаткова накладна №ВД-5167\nвід 13 жовтня 2026 р.\nТовар Кількість Ціна Сума\n"))
assert photo["Документ"] == "Видаткова накладна" and photo["Номер"] == "ВД-5167" and photo["Дата"] == "13.10.2026", photo
assert photo["Постачальник"] == 'ТОВ "Ромашка"', photo
assert photo.get("Покупець: код") == "ЄДРПОУ 1234567890" and "Постачальник: код" not in photo, photo
assert photo["Покупець"] == "ФОП Іванов І. І." and photo["Договір"].startswith("№ ВД 22-12-2022/1"), photo
assert jsonexport.parse_contract(photo["Договір"])["Номер"] == "ВД 22-12-2022/1"

# ---- GUI-потік: xlsx -> JSON-файл
SRC = os.path.join(tempfile.gettempdir(), "tc_test_json.xlsx")
OUT = os.path.join(tempfile.gettempdir(), "tc_test_json.json")
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Товари"
ws.append(["Артикул", "Найменування", "Кількість", "Ціна", "Сума"])
ws.append(["А1", "Мило", 3, 10, 30])
ws.append(["А2", "Крем", 2, 5.5, 11])
wb.save(SRC)

app = App()
app.file_path = SRC
app.reload()
app.tables_list.selection_clear(0, "end")
app.tables_list.selection_set(0)
app.format_var.set("json")
app._on_format_change()
assert app.map_profile() == "upr"
document = app.json_document(app.selected_tables())
jsonexport.write_json(document, OUT)
with open(OUT, encoding="utf-8") as f:
    data = json.load(f)
assert [i["Наименование"] for i in data["Товары"]] == ["Мило", "Крем"], data["Товары"]
assert data["Товары"][1]["Цена"] == 5.5 and data["Товары"][0]["Сумма"] == 30
assert data["Источник"]["Тип"] == "excel"
assert json.loads(app.json_preview(app.selected_tables()[0]))[0]["Артикул"] == "А1"
assert app.assistant_hints()[0].startswith("Обробка: УпрИмпортИзExcel")
os.remove(SRC)
os.remove(OUT)
app.destroy()
print("ВСІ ПЕРЕВІРКИ JSON ПРОЙДЕНО")
