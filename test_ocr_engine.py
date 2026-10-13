"""Автотест рушія для української (RapidOCR як окремий пакет): установка з архіву, виклик виконавця,
вибір рушія, індикатор і кнопка в GUI. Реальний виконавець (134 МБ) у тесті не потрібен: підміняється."""
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

os.environ["TC_OCR_DIR"] = os.path.join(tempfile.mkdtemp(), "ocr")

import ocr_rapid
import scans

tmp = Path(tempfile.mkdtemp())
system32 = Path(os.environ["WINDIR"]) / "System32"

# ---- 1. установка з архіву (file://), прогрес, версія
pack = tmp / "pack.zip"
with zipfile.ZipFile(pack, "w") as z:
    z.write(system32 / "hostname.exe", "ocr_worker.exe")
    z.writestr("version.txt", "9.9\n")
assert not ocr_rapid.is_installed() and ocr_rapid.installed_version() == ""
progress = []
version = ocr_rapid.install(pack.as_uri(), progress=lambda done, total: progress.append((done, total)))
assert version == "9.9" and ocr_rapid.is_installed() and progress and progress[-1][0] == progress[-1][1] > 0, (version, progress)
assert ocr_rapid.install(pack.as_uri()) == "9.9", "повторна установка замінює пакет"

bad = tmp / "bad.zip"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("../evil.txt", "x")
    z.writestr("ocr_worker.exe", "x")
try:
    ocr_rapid.install(bad.as_uri())
    raise AssertionError("архів зі шляхом поза каталогом має відхилятись")
except RuntimeError as exc:
    assert "Небезпечний" in str(exc)
empty = tmp / "empty.zip"
with zipfile.ZipFile(empty, "w") as z:
    z.writestr("readme.txt", "x")
try:
    ocr_rapid.install(empty.as_uri())
    raise AssertionError("архів без виконавця має відхилятись")
except RuntimeError as exc:
    assert "ocr_worker.exe" in str(exc)
assert ocr_rapid.is_installed(), "невдала установка не має ламати встановлений пакет"
assert not [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("tc_ocr_pack_")], "тимчасові файли видаляються"

# ---- 2. виклик виконавця (підмінений скриптом, що пише JSON у форматі справжнього)
fake = tmp / "fake_worker.py"
fake.write_text(
    "import json, sys\n"
    "def result(tag):\n"
    "    words = [{'t': tag, 'x0': 10, 'x1': 120, 'top': 5, 'bottom': 30}, {'t': 'Ціна', 'x0': 200, 'x1': 260, 'top': 6, 'bottom': 31}]\n"
    "    return {'engine': 'fake 1.0', 'angle': 0.0, 'size': [300, 100], 'words': words}\n"
    "if sys.argv[1] == '--batch':\n"
    "    data = [result('стор' + str(i)) for i, _ in enumerate(sys.argv[3:], 1)]\n"
    "    json.dump(data, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False)\n"
    "else:\n"
    "    json.dump(result('Кількість'), open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False)\n",
    encoding="utf-8",
)
ocr_rapid.worker_command = lambda: [sys.executable, str(fake)]
img = Image.new("RGB", (300, 100), "white")
words, info = ocr_rapid.recognize(img)
assert words == [
    {"text": "Кількість", "x0": 10, "x1": 120, "top": 5, "bottom": 30},
    {"text": "Ціна", "x0": 200, "x1": 260, "top": 6, "bottom": 31},
], words
assert info["lang"] == "uk" and info["engine"] == "fake 1.0", info

failing = tmp / "failing_worker.py"
failing.write_text("import sys\nprint('ModelError: немає моделі', file=sys.stderr)\nsys.exit(1)\n", encoding="utf-8")
many = ocr_rapid.recognize_many([img, img, img])
assert [w[0][0]["text"] for w in many] == ["стор1", "стор2", "стор3"] and many[0][1]["lang"] == "uk", many
ocr_rapid.worker_command = lambda: [sys.executable, str(failing)]
try:
    ocr_rapid.recognize(img)
    raise AssertionError("помилка виконавця має передаватись")
except RuntimeError as exc:
    assert "немає моделі" in str(exc)
ocr_rapid.worker_command = lambda: [sys.executable, str(fake)]

# ---- 3. вибір рушія й примітки
assert scans.resolve_engine("auto") == "rapid" and scans.resolve_engine("windows") == "windows"
words, info = scans.recognize_image(img, engine="auto")
assert info["engine_kind"] == "rapid" and words[0]["text"] == "Кількість"
assert len(scans.notes_for({"engine_kind": "rapid"})) == 1
assert len(scans.notes_for({"engine_kind": "windows"})) == 2 and "Windows OCR" in scans.notes_for({"engine_kind": "windows"})[1]
real_dir = os.environ["TC_OCR_DIR"]
os.environ["TC_OCR_DIR"] = os.path.join(tempfile.mkdtemp(), "none")
assert scans.resolve_engine("auto") == "windows", "без пакета - Windows OCR"
os.environ["TC_OCR_DIR"] = real_dir

# ---- 4. GUI: індикатор, кнопка, установка
import app as appmod  # noqa: E402

recorded = []
appmod.messagebox.askyesno = lambda *a, **k: recorded.append(("ask", a)) or True
appmod.messagebox.showinfo = lambda *a, **k: recorded.append(("info", a))
appmod.messagebox.showwarning = lambda *a, **k: recorded.append(("warn", a))
appmod.ocr_windows.available_languages = lambda timeout=30: ["en-US", "ru"]

gui = appmod.App()
gui.update()


def state():
    return gui.ocr_label.cget("text"), gui.ocr_label.cget("fg"), gui.ocr_btn.winfo_manager() == "pack"


gui.set_ocr_status(True, None)
text, color, button = state()
assert "встановлено ✓" in text and "v9.9" in text and color == "#2e7d32" and not button, state()
gui.set_ocr_status(False, ("ok", ["en-US", "ru"]))
text, color, button = state()
assert "не встановлено" in text and "Windows OCR" in text and color == "#b26a00" and button, state()
gui.set_ocr_status(False, ("err", "немає PowerShell"))
text, color, button = state()
assert "недоступне" in text and color == "#c62828" and button, state()

# натискання "Встановити": підтвердження -> завантаження з прогресом -> повторна перевірка
os.environ["TC_OCR_DIR"] = os.path.join(tempfile.mkdtemp(), "fresh")
gui.set_ocr_status(False, ("ok", ["ru"]))
calls = []


def fake_install(url=None, progress=None, **kwargs):
    calls.append("install")
    for done in (30, 100):
        progress(done, 100)
        time.sleep(0.4)
    os.makedirs(ocr_rapid.install_dir(), exist_ok=True)
    open(os.path.join(ocr_rapid.install_dir(), ocr_rapid.WORKER_NAME), "wb").close()


ocr_rapid.install = fake_install
gui._install_ocr()
seen = []
deadline = time.time() + 20
while (gui._ocr_busy or "встановлено ✓" not in gui.ocr_label.cget("text")) and time.time() < deadline:
    gui.update()
    seen.append(gui.ocr_label.cget("text"))
    time.sleep(0.05)
assert calls == ["install"], calls
assert any("завантаження... 30%" in t for t in seen), seen[:5]
assert recorded[0][0] == "ask" and "без прав адміністратора" not in recorded[0][1][1] and "адміністратора" in recorded[0][1][1]
assert any(kind == "info" and "встановлено" in a[1] for kind, a in recorded), recorded
text, color, button = state()
assert "встановлено ✓" in text and color == "#2e7d32" and not button, state()

# невдала установка
os.environ["TC_OCR_DIR"] = os.path.join(tempfile.mkdtemp(), "failed")
ocr_rapid.install = lambda url=None, progress=None, **k: (_ for _ in ()).throw(OSError("немає мережі"))
gui.set_ocr_status(False, ("ok", ["ru"]))
gui._install_ocr()
deadline = time.time() + 15
while gui._ocr_busy and time.time() < deadline:
    gui.update()
    time.sleep(0.05)
assert recorded[-1][0] == "warn" and "немає мережі" in recorded[-1][1][1], recorded[-1]
deadline = time.time() + 10
while "не встановлено" not in gui.ocr_label.cget("text") and time.time() < deadline:
    gui.update()
    time.sleep(0.05)
text, color, button = state()
assert "не встановлено" in text and button, state()
gui.destroy()
print("ВСІ ПЕРЕВІРКИ РУШІЯ OCR ПРОЙДЕНО")
