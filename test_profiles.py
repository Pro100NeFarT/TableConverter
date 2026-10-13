"""Автотест профілів 1С, підбору колонок, контролю, підказок налаштувань і GUI-потоку."""
import csv
import io
import os
import tempfile
import time

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

os.environ["TC_CONFIG_DIR"] = tempfile.mkdtemp()

import checks
import converter
import hints
import profiles
import sources

HEADER = ["№", "Товари (Послуги)", "Кількість", "Кількість_2", "Ціна", "Сума"]
PREPARED = [
    HEADER,
    ["1", "Принтер етикеток", "1,000", "шт", "3 600,00", "3 600,00"],
    ["2", "Прайс-чекер 8'", "1", "шт", "18 900,00", "18 900,00"],
    ["", "", "", "", "Разом:", "22 500,00"],
]

# ---- 1. підбір колонок
upr = profiles.detect_mapping(HEADER, PREPARED[1:], profiles.detectable_fields("upr"))
assert upr["Наименование"] == "Товари (Послуги)" and upr["Количество"] == "Кількість", upr
assert upr["Единица"] == "Кількість_2" and upr["Цена"] == "Ціна" and upr["Сумма"] == "Сума", upr
assert "НомерСтроки" not in upr
old = profiles.detect_mapping(HEADER, PREPARED[1:], profiles.detectable_fields("old"))
assert old["НомерСтроки"] == "№" and old["Количество"] == "Кількість", old
by_content = profiles.detect_mapping(["a", "b", "c"], [["x", "Назва товару довга", "10"], ["y", "Інший довгий товар", "5"]], ["Наименование"])
assert by_content["Наименование"] == "b", by_content

# ---- 2. застосування профілю
rows = profiles.apply_profile(PREPARED, "upr", upr)
assert rows[0] == profiles.PROFILES["upr"]["fields"] and len(rows) == 3, rows  # підсумковий рядок виключено
f = {name: i for i, name in enumerate(rows[0])}
assert rows[1][f["Наименование"]] == "Принтер етикеток" and rows[1][f["Количество"]] == "1"  # 1,000 -> 1
assert rows[1][f["Единица"]] == "шт" and rows[1][f["Цена"]] == "3600.00" and rows[1][f["Сумма"]] == "3600.00"
assert len(rows[1]) == 17
rows_old = profiles.apply_profile(PREPARED, "old", old)
assert len(rows_old[0]) == 19 and rows_old[1][0] == "1" and rows_old[1][rows_old[0].index("Количество")] == "1"

assert profiles.split_quantity("1 шт") == ("1", "шт")
assert profiles.split_quantity("0,5") == ("0.5", None)
assert profiles.split_quantity("12 000,000") == ("12000", None)
assert profiles.split_quantity("abc") == ("abc", None)

# ---- 3. збережений підбір по постачальнику
assert profiles.load_saved("ІПН 1", "upr") is None
custom = dict(upr, Артикул="№")
profiles.save_mapping("ІПН 1", "upr", custom)
again = profiles.resolve_mapping(HEADER, PREPARED[1:], "upr", "ІПН 1")
assert again["Артикул"] == "№" and again["Цена"] == "Ціна"
other = profiles.resolve_mapping(HEADER, PREPARED[1:], "upr", "ІПН 2")
assert other["Артикул"] is None

# ---- 4. контроль
info = {"Разом": "22 500,00", "Кількість найменувань": "2"}
res = checks.run_checks(PREPARED, upr, info)
assert not [m for lvl, m in res if lvl == "error"], res
assert any("збігається з «Разом»" in m for _, m in res)
bad = checks.run_checks(PREPARED, upr, {"Разом": "22 000,00", "Кількість найменувань": "3"})
assert sum(1 for lvl, _ in bad if lvl == "error") == 2, bad
frac = [HEADER, ["1", "Сир", "0,5", "кг", "100,00", "50,00"], ["2", "Хліб", "2", "шт", "10,00", "25,00"]]
fr = checks.run_checks(frac, upr, {})
assert not any("Дробова" in m for _, m in fr), fr  # дробова кількість (0,5) - не привід для попередження
assert any(lvl == "warn" and "× ціна ≠ сума" in m for lvl, m in fr), fr
broken = checks.run_checks([HEADER, ["1", "Товар", "x", "шт", "1", "1"]], upr, {})
assert any(lvl == "error" and "Не розпізнано число" in m for lvl, m in broken), broken
assert checks.summary(res) == "✓" and checks.summary(bad).startswith("✗")

# ---- 5. підказки
lines = hints.csv_lines("upr", ";")
text = "\n".join(lines)
assert "Роздільник csv (поле на вкладці «Настройка»): ;" in text and "17. ХарактеристикаНаименование" in text
raw_rows = [r for r in PREPARED]
table_only = "\n".join(hints.excel_lines_table_only([("Стор. 1, табл. 1", raw_rows, HEADER, upr)]))
assert "ПерваяСтрокаСТоваром = 2" in table_only and "ПоследняяСтрокаСТоваром = 3   (або КоличествоСтрокПодвала = 1)" in table_only
assert "Наименование = 2" in table_only and "Количество = 3" in table_only and "Сумма = 6" in table_only, table_only

# ---- 6. PDF: розкладка 1 в 1 + підказка + GUI
pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
body = ParagraphStyle("b", parent=getSampleStyleSheet()["Normal"], fontName="Arial", fontSize=10)
pdf = os.path.join(tempfile.gettempdir(), "tc_profile_test.pdf")
data = [["№", "Товари (Послуги)", "Кількість", "", "Ціна", "Сума"],
        ["1", "Принтер етикеток", "1", "шт", "3 600,00", "3 600,00"],
        ["2", "Прайс-чекер", "2", "шт", "18 900,00", "37 800,00"]]
t = Table(data, colWidths=[25, 190, 55, 35, 70, 70])
t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTNAME", (0, 0), (-1, -1), "Arial"),
                       ("FONTSIZE", (0, 0), (-1, -1), 10), ("SPAN", (2, 0), (3, 0))]))
SimpleDocTemplate(pdf, pagesize=A4).build([
    Paragraph("Видаткова накладна № 277 від 23 вересня 2026 р.", body),
    Paragraph("Постачальник ФОП Петренко Іван, ІПН 1234567890, р/р UA213223130000026007233566001", body),
    Paragraph("Покупець ФОП Сидоренко Олег, 23100, м. Жмеринка", body),
    Spacer(1, 10), t,
    Paragraph("Разом: 41 400,00", body),
    Paragraph("Всього найменувань 2, на суму 41 400,00 грн.", body),
    Spacer(1, 20), Paragraph("Відвантажив: ____", body),
])

tables = sources.load_pdf_tables(pdf, mode="lines")
assert len(tables) == 1 and tables[0].rows[0][2] == "Кількість"
sheets = sources.load_pdf_layout(pdf)
assert len(sheets) == 1 and sheets[0].meta, sheets
meta = sheets[0].meta[0]
header_row_excel = meta["header_row"] + 1
prepared = converter.prepare_rows(tables[0].rows, tables[0].merges, fill_merges=True)
mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr", "")
lay = "\n".join(hints.excel_lines_layout(sheets, [(tables[0], prepared[0], mapping)]))
print(lay)
assert f"ПерваяСтрокаСТоваром = {header_row_excel + 1}" in lay, (lay, header_row_excel)
assert f"ПоследняяСтрокаСТоваром = {meta['last_row'] + 1}" in lay
w = sheets[0]
name_col = next(c for c in range(w.n_cols) if w.rows[meta["header_row"]][c].startswith("Товари"))
assert f"Наименование = {name_col + 1}" in lay, (lay, name_col)

import app as appmod  # noqa: E402

app = appmod.App()
app.file_path = pdf
app.reload()
deadline = time.time() + 60
while app._loading and time.time() < deadline:
    app.update()
    time.sleep(0.05)
assert not app._loading and app.tables
assert dict(app.doc_info)["Номер"] == "277" and app.supplier_key() == "ІПН 1234567890"

app.profile_var.set(appmod.profiles.PROFILES["upr"]["title"])
app._on_profile_change()
app.analyze()
assert app.get_selected_delimiter() == ";"
out = app.output_rows(app.tables[0], ";")
assert len(out[0]) == 17 and len(out) == 3, out
assert app.preview_for(app.tables[0]).splitlines()[1].startswith(";;;Принтер етикеток;;1;шт;;;;;;;;3600.00;3600.00")
groups = app.assistant_checks()
assert groups and not [m for lvl, m in groups[0][1] if lvl == "error"], groups
csv_hint = "\n".join(app.assistant_hints())
assert "Роздільник csv" in csv_hint

app.format_var.set("xlsx")
app.only_table_var.set(False)
app._on_format_change()
xlsx_hint = "\n".join(app.assistant_hints())
assert "Excel 1 в 1" in xlsx_hint and "ПерваяСтрокаСТоваром" in xlsx_hint, xlsx_hint
app.only_table_var.set(True)
tbl_hint = "\n".join(app.assistant_hints())
assert "ПерваяСтрокаСТоваром = 2" in tbl_hint and "Excel: лише таблиця" in tbl_hint, tbl_hint
app.format_var.set("csv")
app._on_format_change()

app._show_info("hints")
win = app._info_win
assert win.winfo_exists() and [win.notebook.tab(t, "text") for t in win.notebook.tabs()][1].startswith("Контроль ✓")
app.update()

dlg = appmod.assistant.ColumnsDialog(app, app.tables[0])
dlg.vars["Артикул"].set("№")
dlg._changed()
assert app.mapping_for(app.tables[0])["Артикул"] == "№"
dlg._save()
assert profiles.load_saved(app.supplier_key(), "upr")["Артикул"] == "№"
dlg._auto()
assert app.mapping_for(app.tables[0])["Артикул"] is None
dlg.destroy()
app.update()

app.destroy()
os.remove(pdf)
print("ВСІ ПЕРЕВІРКИ ПРОФІЛІВ ПРОЙДЕНО")
