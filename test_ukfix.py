"""Виправлення українських літер після OCR за словником (потрібен pymorphy3; без нього тест пропускається)."""
import ukfix

if not ukfix.available():
    print("pymorphy3 не встановлено - пропущено")
    raise SystemExit(0)


def words(*texts):
    return [{"text": t, "x0": 0, "x1": 1, "top": 0, "bottom": 1} for t in texts]


# типові помилки: и замість і, е замість є, регістр зберігається
assert ukfix.fix_word("ФИЗИЧНА") == "ФІЗИЧНА"
assert ukfix.fix_word("правільність") == "правильність"
assert ukfix.fix_word("Підприемець") == "Підприємець"
assert ukfix.fix_word("операций") == "операцій"
# відомі слова, короткі абревіатури, невідомі слова без єдиного варіанта - без змін
for same in ("Кількість", "накладна", "ЄДРПОУ", "ТОВ", "ВУДВІН", "Gigant", "самонарізаючий"):
    assert ukfix.fix_word(same) == same, same

# документ вважається українським за літерами і/ї/є/ґ: у російському тексті нічого не міняємо
ukrainian = words("Видаткова", "накладна", "Кількість", "Ціна", "ФИЗИЧНА", "Підстава", "Договір")
fixed, changes = ukfix.fix_words(ukrainian)
assert fixed[4]["text"] == "ФІЗИЧНА" and changes == [("ФИЗИЧНА", "ФІЗИЧНА")], changes
russian = words("Накладная", "Количество", "Цена", "физическое", "лицо", "Шпаклевка")
fixed, changes = ukfix.fix_words(russian)
assert changes == [] and fixed == russian

# коди й змішані токени не чіпаються
mixed = words("Кількість", "Ціна", "Сума", "Підстава", "10L4213-2", "FD", "3,5х35", "ФИЗИЧНА")
fixed, changes = ukfix.fix_words(mixed)
assert [w["text"] for w in fixed][4:7] == ["10L4213-2", "FD", "3,5х35"]
assert ukfix.fix_text("(ЦБ) РН, 4.2х13")[1] == []
print("ВСІ ПЕРЕВІРКИ ВИПРАВЛЕННЯ УКРАЇНСЬКИХ ЛІТЕР ПРОЙДЕНО")
