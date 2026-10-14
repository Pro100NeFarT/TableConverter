"""
Рушій розпізнавання для української (RapidOCR, модель PP-OCRv5 для кирилиці) як окремий пакет:
програма завантажує ocr_worker.exe одним натисканням «Встановити» (права адміністратора не потрібні) і викликає
його для кожного зображення. Вбудований Windows OCR не вміє українські і/ї/є/ґ, цей рушій - вміє.
"""
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile

PACK_URL = "https://github.com/Pro100NeFarT/TableConverter/releases/download/ocr-pack/TableConverter-OCR.zip"
PACK_SIZE_MB = 130
WORKER_NAME = "ocr_worker.exe"
USER_AGENT = "TableConverter"


def install_dir():
    base = os.environ.get("TC_OCR_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "TableConverter", "ocr"
    )
    return base


def worker_command():
    return [os.path.join(install_dir(), WORKER_NAME)]


def is_installed():
    return os.path.isfile(os.path.join(install_dir(), WORKER_NAME))


def installed_version():
    try:
        with open(os.path.join(install_dir(), "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def enhance(img):
    """Автоконтраст у відтінках сірого: вирівнює освітлення фото, на чистих сканах нічого не змінює."""
    from PIL import ImageOps

    return ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")


def recognize(img, timeout=600):
    """Слова зображення (PIL.Image): {'text','x0','x1','top','bottom'} у пікселях. Нахил виправляє сам виконавець.
    Повертає (слова, {'lang': 'uk', 'engine': ..., 'angle': ...})."""
    token = uuid.uuid4().hex
    src, out = (os.path.join(tempfile.gettempdir(), f"tc_rapid_{token}{ext}") for ext in (".png", ".json"))
    try:
        enhance(img).save(src)
        proc = subprocess.run(
            worker_command() + [src, out],
            capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "Рушій OCR не повернув результат")
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
    finally:
        for path in (src, out):
            try:
                os.remove(path)
            except OSError:
                pass
    return _to_words(data)


def _to_words(data):
    words = [
        {"text": w["t"], "x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"]}
        for w in data.get("words", [])
    ]
    return words, {"lang": "uk", "engine": data.get("engine", "rapidocr"), "angle": data.get("angle")}


def recognize_many(images, timeout=1800):
    """Кілька зображень (PIL.Image) одним запуском виконавця: [(слова, інфо), ...] у тому ж порядку."""
    token = uuid.uuid4().hex
    out = os.path.join(tempfile.gettempdir(), f"tc_rapid_{token}.json")
    sources = [os.path.join(tempfile.gettempdir(), f"tc_rapid_{token}_{i}.png") for i in range(len(images))]
    try:
        for img, path in zip(images, sources):
            enhance(img).save(path)
        proc = subprocess.run(
            worker_command() + ["--batch", out] + sources,
            capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "Рушій OCR не повернув результат")
        with open(out, encoding="utf-8") as f:
            results = json.load(f)
    finally:
        for path in sources + [out]:
            try:
                os.remove(path)
            except OSError:
                pass
    return [_to_words(r) for r in results]


def install(url=PACK_URL, progress=None, timeout=120):
    """Завантажує й розпаковує пакет (zip з ocr_worker.exe і version.txt) у каталог програми.
    progress(отримано_байт, всього_байт). Повертає версію пакета."""
    token = uuid.uuid4().hex
    archive = os.path.join(tempfile.gettempdir(), f"tc_ocr_pack_{token}.zip")
    staging = os.path.join(tempfile.gettempdir(), f"tc_ocr_pack_{token}")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response, open(archive, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        os.makedirs(staging)
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                target = os.path.realpath(os.path.join(staging, name))
                if not target.startswith(os.path.realpath(staging) + os.sep) and target != os.path.realpath(staging):
                    raise RuntimeError(f"Небезпечний шлях в архіві: {name}")
            z.extractall(staging)
        if not os.path.isfile(os.path.join(staging, WORKER_NAME)):
            raise RuntimeError(f"В архіві немає {WORKER_NAME}")
        target_dir = install_dir()
        shutil.rmtree(target_dir, ignore_errors=True)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        shutil.move(staging, target_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            os.remove(archive)
        except OSError:
            pass
    return installed_version()
