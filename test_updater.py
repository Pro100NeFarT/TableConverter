"""Автотест перевірки версій і самооновлення (без мережі: file://-адреси та підміна exe в тимчасовій теці)."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import app_version
import updater

root = Path(__file__).parent

# ---- version.txt і APP_VERSION мають збігатись (інакше оновлення "по колу")
assert (root / "version.txt").read_text(encoding="utf-8").strip() == app_version.APP_VERSION, "version.txt != APP_VERSION"

# ---- порівняння версій
assert updater.parse_version("1.10.2") == (1, 10, 2) and updater.parse_version("v2.0") == (2, 0)
assert updater.parse_version("abc") is None
assert updater.check("1.0.0", fetch=lambda: "1.0.1") == ("newer", "1.0.1")
assert updater.check("1.0.0", fetch=lambda: "1.0.0\n") == ("current", "1.0.0")
assert updater.check("1.10.0", fetch=lambda: "1.9.9") == ("current", "1.9.9")  # 1.10 > 1.9, а не лексикографічно
assert updater.check("1.0.0", fetch=lambda: "<html>404</html>")[0] == "error"


def boom():
    raise OSError("нема мережі")


assert updater.check("1.0.0", fetch=boom) == ("error", "нема мережі")

# ---- мережеві виклики через file://
tmp = Path(tempfile.mkdtemp(prefix="Тест оновлення "))
(tmp / "version.txt").write_text("﻿9.9.9\n", encoding="utf-8")
updater.VERSION_URL = (tmp / "version.txt").as_uri()
assert updater.fetch_remote_version() == "9.9.9"
assert updater.check("1.0.0")[0] == "newer"
payload = os.urandom(700_000)
(tmp / "src.bin").write_bytes(payload)
updater.download((tmp / "src.bin").as_uri(), str(tmp / "dl.bin"))
assert (tmp / "dl.bin").read_bytes() == payload

# ---- підміна exe скриптом (теча з кирилицею; "exe" - копії системних утиліт з унікальним ім'ям)
system32 = Path(os.environ["WINDIR"]) / "System32"
name = f"TCtest_{os.getpid()}.exe"
exe = tmp / name
new = tmp / (name + ".new")
shutil.copy(system32 / "hostname.exe", exe)
shutil.copy(system32 / "whoami.exe", new)
expected = hashlib.sha256(new.read_bytes()).hexdigest()
assert hashlib.sha256(exe.read_bytes()).hexdigest() != expected

script = updater.update_script(str(exe), str(new))
assert f'tasklist /fi "IMAGENAME eq {name}"' in script and f'move /y "{new}" "{exe}"' in script
bat = updater.launch_update(str(exe), str(new))
deadline = time.time() + 30
while time.time() < deadline and (new.exists() or os.path.exists(bat)):
    time.sleep(0.3)
assert not new.exists(), "файл .new має бути підмінений"
assert hashlib.sha256(exe.read_bytes()).hexdigest() == expected, "exe не оновився"
assert not os.path.exists(bat), "bat має видалити себе"
print("Підміна exe скриптом: ок")

assert updater.can_self_update() is False  # у тесті - не зібраний exe

# ---- GUI: підсвічування версії та ручна перевірка
import app as appmod  # noqa: E402

recorded = []
appmod.messagebox.showinfo = lambda *a, **k: recorded.append(("info", a))
appmod.messagebox.showwarning = lambda *a, **k: recorded.append(("warn", a))
appmod.messagebox.askyesno = lambda *a, **k: recorded.append(("ask", a)) or False

gui = appmod.App()
assert gui.version_label.cget("text") == f"v{app_version.APP_VERSION}"

gui.on_update_result(("current", "1.0.0"), manual=False)
assert not recorded
gui.on_update_result(("current", "1.0.0"), manual=True)
assert recorded[-1][0] == "info" and "найновіша" in recorded[-1][1][1]
gui.on_update_result(("error", "x"), manual=False)
assert len(recorded) == 1  # тихо
gui.on_update_result(("error", "x"), manual=True)
assert recorded[-1][0] == "warn"

gui.on_update_result(("newer", "9.9.9"), manual=False)
assert gui.version_label.cget("text").endswith("↑") and gui._pending_update == "9.9.9"
count = len(recorded)
gui._on_version_click()  # є оновлення -> пропозиція (askyesno повертає False)
assert recorded[-1][0] == "ask" and "9.9.9" in recorded[-1][1][1] and len(recorded) == count + 1
gui._perform_update()  # не exe -> пояснення, без завантаження
assert recorded[-1][0] == "info" and "git pull" in recorded[-1][1][1]
gui.destroy()

shutil.rmtree(tmp, ignore_errors=True)
print("ВСІ ПЕРЕВІРКИ ОНОВЛЕННЯ ПРОЙДЕНО")
