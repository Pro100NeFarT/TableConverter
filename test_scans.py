"""Автотест скан/фото: виправлення типових помилок OCR, таблиця й реквізити з зображення та скан-PDF,
GUI-шлях. OCR-частина потребує вбудованого розпізнавання Windows; без нього - пропускається."""
import os
import tempfile
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

os.environ["TC_OCR_DIR"] = os.path.join(tempfile.mkdtemp(), "none")  # без рушія для української: перевіряється Windows OCR

import checks
import converter
import profiles
import scans

# ---- 1. виправлення типових помилок (без OCR)
assert scans.fix_word("NQ") == "№" and scans.fix_word("№") == "№"
assert scans.fix_word("Кјлькјсть") == "Кількість" and scans.fix_word("'ван") == "Іван" and scans.fix_word("'ПН") == "ІПН"
assert scans.fix_word("Іван") == "Іван" and scans.fix_word("м.Київ") == "м.Київ"
assert scans.fix_numeric_cell("з 600,00") == "3 600,00" and scans.fix_numeric_cell("1О") == "10"
assert scans.fix_numeric_cell("Принтер") == "Принтер" and scans.fix_numeric_cell("з") == "3"
assert scans.fix_numeric_cell("125,50") == "125,50" and scans.fix_numeric_cell("ab 12") == "ab 12"
assert scans.fix_header_text("Найменування p06iT, послуг") == "Найменування робіт, послуг"
assert scans.fix_header_text("Товари (Послуги)") == "Товари (Послуги)"
assert scans.fix_header_text("Труба PN16 XPrinter-Q260H") == "Труба PN16 XPrinter-Q260H"  # латиниця в назвах не чіпається
assert scans.is_image("a.JPG") and scans.is_image("b.tiff") and not scans.is_image("c.pdf")

# ---- 1б. таблиця-форма за заголовком і вмістом (без OCR): акт з одним рядком, частково втрачена шапка


def W(text, x0, x1, top):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 20}


fake = [
    W("Акт", 100, 150, 100), W("N2", 160, 200, 100), W("341", 210, 260, 100), W("31", 400, 430, 100),
    W("травня", 440, 520, 100), W("2024", 530, 580, 100), W("р.", 590, 610, 100),
    W("Найменування", 200, 330, 300), W("робіт,", 340, 400, 300), W("послуг", 410, 480, 300), W("Сума", 900, 960, 300),
    W("1", 130, 140, 340), W("Інформаційні", 210, 320, 340), W("послуги", 330, 400, 340),
    W("2,25", 600, 640, 340), W("год", 650, 680, 340), W("1", 760, 770, 340), W("002,22", 775, 840, 340),
    W("2", 900, 910, 340), W("255,00", 915, 980, 340),
    W("Разом:", 820, 880, 420), W("2", 900, 910, 420), W("255,00", 915, 980, 420),
    W("Загальна", 120, 200, 480), W("вартість", 210, 280, 480),
]
fixed = scans.fix_words(fake)
assert [w["text"] for w in fixed][1] == "№", [w["text"] for w in fixed][:3]  # "N2" перед числом - знак номера
form = scans.form_table_from_words(fixed, "Стор. 1")
assert form is not None and form.rows[0][1] == "Найменування робіт, послуг" and form.rows[0][2:] == ["Кількість", "Од.", "Ціна", "Сума"], form
assert form.rows[1] == ["1", "Інформаційні послуги", "2,25", "год", "1 002,22", "2 255,00"], form.rows
assert len(form.rows) == 2, "рядок 'Разом' не має потрапити в таблицю"
tables_fake = scans.tables_from_image_words(fixed, "Стор. 1")
assert len(tables_fake) == 1 and tables_fake[0].selected
prepared = converter.prepare_rows(form.rows, [], fill_merges=True)
mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr", "")
res = checks.run_checks(prepared, mapping, {"Разом": "2 255,00"})
assert [m for lvl, m in res if lvl == "error"] == [], res
assert not any("Дробова" in m for _, m in res), res  # дробова кількість - не привід для попередження
lines_fake = scans.lines_from_words(fixed)
import docinfo as _docinfo  # noqa: E402

info_fake = dict(_docinfo.parse_header_text("\n".join(lines_fake), "act.png"))
assert info_fake["Документ"] == "Акт" and info_fake["Номер"] == "341" and info_fake["Дата"] == "31.05.2024", info_fake
assert info_fake["Разом"] == "2 255,00", info_fake
print("форма за заголовком (без OCR): ок")

# ---- 2. синтетичний скан
font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 30)
small = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 26)
img = Image.new("RGB", (1654, 2339), "white")
d = ImageDraw.Draw(img)
d.text((120, 120), "Видаткова накладна № 277 від 23 вересня 2026 р.", font=font, fill="black")
d.text((120, 190), "Постачальник ФОП Петренко Іван Іванович, ІПН 1234567890", font=small, fill="black")
d.text((120, 240), "Покупець ФОП Сидоренко Олег Васильович, м. Жмеринка", font=small, fill="black")
bounds = [120, 190, 740, 900, 990, 1190, 1400, 1534]
rows = [["№", "Товари (Послуги)", "Кількість", "Од.", "Ціна", "Сума"],
        ["1", "Принтер етикеток XPrinter-Q260H", "1", "шт", "3 600,00", "3 600,00"],
        ["2", "Прайс-чекер 8 дюймів кріплення", "2", "шт", "18 900,00", "37 800,00"],
        ["3", "Рулон етикеток 58х40 мм", "10", "шт", "125,50", "1 255,00"],
        ["4", "Папір чековий 80 мм", "20", "рул", "42,00", "840,00"]]
y0, rh = 330, 62
for r in range(len(rows) + 1):
    d.line([(bounds[0], y0 + r * rh), (bounds[-1], y0 + r * rh)], fill="black", width=2)
for x in bounds:
    d.line([(x, y0), (x, y0 + len(rows) * rh)], fill="black", width=2)
for r, row in enumerate(rows):
    for c, text in enumerate(row):
        d.text((bounds[c] + 10, y0 + r * rh + 14), text, font=small, fill="black")
yy = y0 + len(rows) * rh + 30
d.text((1190, yy), "Разом: 43 495,00", font=font, fill="black")
d.text((120, yy + 70), "Всього найменувань 4, на суму 43 495,00 грн.", font=small, fill="black")

tmp = tempfile.gettempdir()
scan_png = os.path.join(tmp, "tc_test_scan.png")
tilted_jpg = os.path.join(tmp, "tc_test_tilted.jpg")
scan_pdf = os.path.join(tmp, "tc_test_scan.pdf")
img.save(scan_png)
img.rotate(1.6, expand=True, fillcolor="white", resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.8)).save(
    tilted_jpg, quality=85
)
img.save(scan_pdf, "PDF", resolution=200)
assert scans.has_text_layer(scan_pdf) is False


def check_table(tables, label):
    assert tables, f"{label}: таблиць немає"
    t = max(tables, key=lambda x: x.n_rows)
    assert t.n_rows == 5 and t.n_cols == 6, (label, t.n_rows, t.n_cols)
    assert "Товари" in t.rows[0][1], (label, t.rows[0])
    assert t.rows[1][4] == "3 600,00" and t.rows[1][5] == "3 600,00", (label, t.rows[1])  # "з 600,00" виправлено
    prepared = converter.prepare_rows(t.rows, [], fill_merges=True)
    mapping = profiles.resolve_mapping(prepared[0], prepared[1:], "upr", "")
    res = checks.run_checks(prepared, mapping, {"Разом": "43 495,00", "Кількість найменувань": "4"})
    assert not [m for lvl, m in res if lvl != "ok"], (label, res, t.rows, mapping)


try:
    tables, lines, notes = scans.ocr_image(scan_png)
except RuntimeError as exc:
    print("OCR недоступний, пропуск:", exc)
    raise SystemExit(0)

check_table(tables, "скан")
import docinfo  # noqa: E402

info = dict(docinfo.parse_header_text("\n".join(lines), "scan.png"))
assert info["Номер"] == "277" and info["Дата"] == "23.09.2026", info
assert info["Постачальник: код"] == "ІПН 1234567890" and info["Разом"] == "43 495,00", info
assert notes and "OCR" in notes[0]
print("скан: таблиця й реквізити розпізнані")

tables_t, _, _ = scans.ocr_image(tilted_jpg)
check_table(tables_t, "нахилене фото")
print("фото з нахилом 1.6 град: виправлено")

tables_p, lines_p, _ = scans.ocr_pdf(scan_pdf)
check_table(tables_p, "скан-PDF")
assert tables_p[0].name.startswith("Стор. 1")
print("скан-PDF: розпізнано")

# ---- 3. GUI-шлях
import app as appmod  # noqa: E402

app = appmod.App()
app.file_path = scan_png
app.reload()
deadline = time.time() + 120
while app._loading and time.time() < deadline:
    app.update()
    time.sleep(0.05)
assert not app._loading and app._ocr_source and app.tables
assert dict(app.doc_info)["Номер"] == "277"
assert str(app.only_table_cb.cget("state")) == "disabled"
app.profile_var.set(appmod.profiles.PROFILES["upr"]["title"])
app._on_profile_change()
app.analyze()
out = app.output_rows(app.tables[0], ";")
assert out[1][out[0].index("Количество")] == "1" and out[1][out[0].index("Цена")] == "3600.00", out[:2]
assert not [m for lvl, m in app.assistant_checks()[0][1] if lvl == "error"]
app.destroy()

for f in (scan_png, tilted_jpg, scan_pdf):
    os.remove(f)
print("ВСІ ПЕРЕВІРКИ СКАНІВ ПРОЙДЕНО")
