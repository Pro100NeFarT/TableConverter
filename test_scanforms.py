"""Розбір таблиці-форми зі скана/фото за готовими клітинками (без OCR): кілька колонок цін/сум, одиниця
'100 шт' перед кількістю, назва на кілька рядків, рядок підсумків без підпису, виправлення OCR."""
import scans


def cells(*parts):
    """[(x0, x1, текст)] з пар (x0, текст)."""
    return [(x, x + 10 * len(t), t) for x, t in parts]


expected = ("qty", "price", "price", "sum", "sum")
assert scans._header_groups(["Кількість Ціна без Ціна 3 Сума без", "Сума 3"]) == list(expected)
assert scans._numeric_header(list(expected)) == ["Ціна без ПДВ", "Ціна з ПДВ", "Сума без ПДВ", "Сума з ПДВ"]
assert scans._numeric_header(["qty", "price", "sum"]) == ["Ціна", "Сума"]

# рядок: назва з номером, '100 шт' перед кількістю, дві ціни й дві суми
row = scans._parse_form_row(
    cells((64, "1 AB-1 (уп.100 шт.) Гвинт самонарізаючий з"), (398, "100 шT"), (509, "120,000"), (594, "12,05"),
          (656, "14.46"), (721, "1446.00"), (804, "1735.20")),
    expected, 1,
)
assert row == ["1", "AB-1 (уп.100 шт.) Гвинт самонарізаючий з", "120,000", "100 шT", "12,05", "14.46", "1446.00", "1735.20"], row

# номер в окремій клітинці, одиниця без пробілу
row = scans._parse_form_row(
    cells((58, "4"), (91, "FD 3,9х70 Шуруп"), (394, "100шт"), (516, "60.000"), (592, "24.20"), (655, "29.04"),
          (717, "1452.00"), (803, "1742.40")),
    expected, 4,
)
assert row[0] == "4" and row[2] == "60.000" and row[3] == "100 шт" and row[7] == "1742.40", row

# звичайна форма: кількість з одиницею в одній клітинці, одна ціна й сума
row = scans._parse_form_row(cells((50, "1"), (90, "Послуга"), (300, "2 шт"), (360, "10,00"), (420, "20,00")),
                            ("qty", "price", "sum"), 1)
assert row == ["1", "Послуга", "2", "шт", "10,00", "20,00"], row

# виправлення OCR
assert scans.fix_unit("шT") == "шт" and scans.fix_unit("1оо шт") == "100 шт" and scans.fix_unit("100 шT") == "100 шт"
assert scans.fix_mixed_script("вiд 22.12.2022") == "від 22.12.2022"
assert scans.fix_mixed_script("FD 3,5") == "FD 3,5"
print("ВСІ ПЕРЕВІРКИ ФОРМ ЗІ СКАНІВ ПРОЙДЕНО")


# ---- таблиця за позиціями слів шапки: Код, ставка ПДВ, 'N шт' в одній комірці, продовження назви, зайва колонка
def line(y, *parts):
    return [{"text": t, "x0": x, "x1": x + 9 * len(t), "top": y, "bottom": y + 14} for x, t in parts]


words = []
words += line(100, (10, "№"), (60, "Код"), (250, "Товар"), (520, "ПДВ"), (580, "Кількість"), (690, "Ціна"), (790, "Сума"), (900, "Вх."), (940, "№"))
rows_data = [
    ("1", "НФ-00000256", "Люк чорний", "20%", "100 шт", "370.00", "37 000,00", "12731"),
    ("2", "НФ-00000257", "Люк зелений", "20%", "80шт", "415,00", "33 200,00", "13039"),
    ("3", "НФ-00000408", "Люк коричневий", "20%", "20 ET", "415,00", "8 300,00", "11245"),
]
y = 140
for n, code, title, vat, qty, price, total, extra in rows_data:
    words += line(y, (10, n), (50, code), (160, title), (500, vat), (590, qty), (690, price), (780, total), (900, extra))
    words += line(y + 18, (165, "(продовження назви)"))
    y += 40
words += line(y, (690, "6 855,00"), (780, "78 500,00"))
words += line(y + 40, (10, "Всього на суму: сімдесят вісім тисяч"))
table = scans.form_table_from_words(words, "тест")
assert table is not None and table.rows[0][:2] == ["№", "Код"], table and table.rows[0]
assert len(table.rows) == 4, table.rows
header = table.rows[0]
qty_i, price_i, sum_i, unit_i = header.index("Кількість"), header.index("Ціна"), header.index("Сума"), header.index("Од.")
assert [r[qty_i] for r in table.rows[1:]] == ["100", "80", "20"], table.rows
assert [r[unit_i] for r in table.rows[1:]] == ["шт", "шт", "шт"], table.rows
assert table.rows[2][price_i] == "415,00" and table.rows[3][sum_i] == "8 300,00", table.rows
assert table.rows[1][1] == "НФ-00000256" and table.rows[1][2] == "Люк чорний (продовження назви)", table.rows[1]
assert all("12731" not in " ".join(r) and "20%" not in " ".join(r) for r in table.rows)
print("ВСІ ПЕРЕВІРКИ ТАБЛИЦІ ЗА ПОЗИЦІЯМИ КОЛОНОК ПРОЙДЕНО")
