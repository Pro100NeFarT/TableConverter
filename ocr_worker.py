"""
Окремий виконавець розпізнавання тексту (збирається в ocr_worker.exe і завантажується програмою за потреби).
Рушій: RapidOCR + модель PP-OCRv5 для кирилиці (у т.ч. українські і/ї/є/ґ), працює офлайн.

Запуск:  ocr_worker.exe <зображення> <вихідний.json>             розпізнати одне зображення
         ocr_worker.exe --batch <вихідний.json> <зобр1> <зобр2> ...  розпізнати кілька (один запуск рушія)
         ocr_worker.exe --version                                  вивести версію
"""
import json
import math
import sys

WORKER_VERSION = "1.1"
MIN_DESKEW, MAX_DESKEW = 0.4, 20.0


def _engine():
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    return RapidOCR(
        params={
            "Rec.lang_type": LangRec.CYRILLIC,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Global.log_level": "error",
        }
    )


def _words(result):
    words = []
    for line in getattr(result, "word_results", None) or ():
        for text, _score, box in line:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            words.append({"t": text, "x0": min(xs), "x1": max(xs), "top": min(ys), "bottom": max(ys), "box": box})
    return words


def _skew(words):
    """Кут нахилу тексту (градуси; додатний - рядок іде вниз праворуч): медіана за верхніми краями слів."""
    angles = []
    for w in words:
        (x0, y0), (x1, y1) = w["box"][0], w["box"][1]
        if x1 - x0 >= 40:
            angles.append(math.degrees(math.atan2(y1 - y0, x1 - x0)))
    if len(angles) < 5:
        return 0.0
    angles.sort()
    return angles[len(angles) // 2]


def recognize(image_path, engine=None):
    import numpy as np
    from PIL import Image, ImageOps

    with Image.open(image_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        engine = engine or _engine()
        words = _words(engine(np.array(img), return_word_box=True))
        angle = _skew(words)
        if MIN_DESKEW <= abs(angle) <= MAX_DESKEW:
            straight = img.rotate(angle, expand=True, fillcolor="white", resample=Image.BICUBIC)
            words = _words(engine(np.array(straight), return_word_box=True))
            img = straight
        size = img.size
    for w in words:
        w.pop("box", None)
    return {"engine": f"rapidocr-cyrillic-ppocrv5 {WORKER_VERSION}", "angle": angle, "size": list(size), "words": words}


def main(argv):
    if len(argv) >= 2 and argv[1] == "--version":
        print(WORKER_VERSION)
        return 0
    try:
        if len(argv) >= 4 and argv[1] == "--batch":
            engine = _engine()
            data = [recognize(path, engine) for path in argv[3:]]
            out = argv[2]
        elif len(argv) == 3:
            data, out = recognize(argv[1]), argv[2]
        else:
            print("Використання: ocr_worker <зображення> <вихідний.json>", file=sys.stderr)
            return 2
    except Exception as exc:  # повідомлення читає програма
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
