"""
Збирає пакет рушія розпізнавання для української: dist/TableConverter-OCR.zip (ocr_worker.exe + version.txt).
Потрібен інтернет (pip і моделі RapidOCR); робочі файли - у build_ocr/ (середовище .venv).

Запуск:  python build_ocr_pack.py
Результат завантажується як файл релізу з тегом ocr-pack (звідти його бере кнопка «Встановити» в програмі):
    gh release create ocr-pack dist/TableConverter-OCR.zip --title "OCR-пакет" --notes "..."      (перший раз)
    gh release upload ocr-pack dist/TableConverter-OCR.zip --clobber                               (оновлення)
"""
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(ROOT, "build_ocr")
VENV = os.path.join(WORK, ".venv")
PY = os.path.join(VENV, "Scripts", "python.exe")
REQUIREMENTS = ["rapidocr", "onnxruntime", "opencv-python-headless", "pillow", "pyinstaller"]


def run(*args, **kwargs):
    print(">", " ".join(map(str, args)))
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def worker_version():
    with open(os.path.join(ROOT, "ocr_worker.py"), encoding="utf-8") as f:
        return re.search(r'WORKER_VERSION = "([^"]+)"', f.read()).group(1)


def main():
    os.makedirs(WORK, exist_ok=True)
    if not os.path.exists(PY):
        run(sys.executable, "-m", "venv", VENV)
    run(PY, "-m", "pip", "install", "--quiet", *REQUIREMENTS)

    # прогрів: моделі завантажуються при першому запуску й потрапляють у збірку разом із пакетом rapidocr
    warmup = os.path.join(WORK, "warmup.png")
    run(PY, "-c", (
        "from PIL import Image, ImageDraw; im = Image.new('RGB', (600, 120), 'white'); "
        "ImageDraw.Draw(im).text((20, 40), 'Test 123', fill='black'); im.save(r'%s')" % warmup))
    run(PY, os.path.join(ROOT, "ocr_worker.py"), warmup, os.path.join(WORK, "warmup.json"))

    run(PY, "-m", "PyInstaller", "--onefile", "--console", "--name", "ocr_worker", "--collect-all", "rapidocr",
        "--distpath", os.path.join(WORK, "dist"), "--workpath", os.path.join(WORK, "build"),
        "--specpath", WORK, "--noconfirm", os.path.join(ROOT, "ocr_worker.py"))

    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    archive = os.path.join(ROOT, "dist", "TableConverter-OCR.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(WORK, "dist", "ocr_worker.exe"), "ocr_worker.exe")
        z.writestr("version.txt", worker_version() + "\n")
    print(f"Готово: {archive} ({os.path.getsize(archive) / 1e6:.0f} МБ), версія виконавця {worker_version()}")


if __name__ == "__main__":
    main()
