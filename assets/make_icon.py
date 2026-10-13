"""Генерує логотип застосунку: документ (зі скан-променем OCR) -> стрілка -> таблиця.
Запуск: python assets/make_icon.py  ->  assets/logo.png, assets/icon.ico"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 4  # supersampling
N = 512


def px(v):
    return int(round(v * S))


def rounded_mask(box, radius, size):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([px(v) for v in box], radius=px(radius), fill=255)
    return mask


def build():
    size = (N * S, N * S)
    img = Image.new("RGBA", size, (0, 0, 0, 0))

    # фон: заокруглений квадрат із градієнтом синій -> бірюзовий
    top, bottom = (21, 101, 192), (0, 137, 123)
    gradient = Image.new("RGBA", size)
    gd = ImageDraw.Draw(gradient)
    for y in range(size[1]):
        t = y / (size[1] - 1)
        gd.line([(0, y), (size[0], y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    img.paste(gradient, (0, 0), rounded_mask((20, 20, 492, 492), 104, size))

    d = ImageDraw.Draw(img)

    # документ зі загнутим кутом
    page = [(66, 104), (196, 104), (240, 148), (240, 404), (66, 404)]
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(px(x + 6), px(y + 8)) for x, y in page], fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(px(7))))
    d = ImageDraw.Draw(img)
    d.polygon([(px(x), px(y)) for x, y in page], fill=(255, 255, 255, 255))
    d.polygon([(px(196), px(104)), (px(196), px(148)), (px(240), px(148))], fill=(207, 216, 220, 255))

    # рядки тексту
    for y, w in ((176, 128), (206, 104), (236, 128)):
        d.rounded_rectangle([px(88), px(y), px(88 + w), px(y + 12)], radius=px(6), fill=(176, 190, 197, 255))
    # таблиця всередині документа
    for r in range(4):
        d.line([(px(88), px(290 + r * 24)), (px(218), px(290 + r * 24))], fill=(144, 164, 174, 255), width=px(3))
    for c in range(3):
        d.line([(px(88 + c * 65), px(290)), (px(88 + c * 65), px(362))], fill=(144, 164, 174, 255), width=px(3))

    # скан-промінь
    beam = Image.new("RGBA", size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(beam)
    bd.rounded_rectangle([px(48), px(262), px(262), px(278)], radius=px(8), fill=(0, 229, 255, 235))
    img.alpha_composite(beam.filter(ImageFilter.GaussianBlur(px(5))))
    img.alpha_composite(beam)
    d = ImageDraw.Draw(img)

    # стрілка
    arrow = [(252, 236), (306, 236), (306, 212), (352, 256), (306, 300), (306, 276), (252, 276)]
    d.polygon([(px(x), px(y)) for x, y in arrow], fill=(255, 193, 7, 255), outline=(255, 160, 0, 255))

    # таблиця-результат
    tx0, ty0, tx1, ty1 = 330, 132, 462, 392
    tshadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(tshadow).rounded_rectangle(
        [px(tx0 + 6), px(ty0 + 8), px(tx1 + 6), px(ty1 + 8)], radius=px(16), fill=(0, 0, 0, 90)
    )
    img.alpha_composite(tshadow.filter(ImageFilter.GaussianBlur(px(7))))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([px(tx0), px(ty0), px(tx1), px(ty1)], radius=px(16), fill=(255, 255, 255, 255))
    d.rounded_rectangle([px(tx0), px(ty0), px(tx1), px(ty0 + 52)], radius=px(16), fill=(46, 125, 50, 255))
    d.rectangle([px(tx0), px(ty0 + 30), px(tx1), px(ty0 + 52)], fill=(46, 125, 50, 255))
    rows = 5
    row_h = (ty1 - (ty0 + 52)) / rows
    for r in range(rows):
        y = ty0 + 52 + r * row_h
        if r % 2 == 0:
            d.rectangle([px(tx0 + 3), px(y), px(tx1 - 3), px(y + row_h)], fill=(232, 245, 233, 255))
        d.line([(px(tx0 + 3), px(y)), (px(tx1 - 3), px(y))], fill=(165, 214, 167, 255), width=px(3))
    colw = (tx1 - tx0) / 3
    for c in (1, 2):
        d.line([(px(tx0 + c * colw), px(ty0 + 6)), (px(tx0 + c * colw), px(ty1 - 6))], fill=(165, 214, 167, 255), width=px(3))
    d.line([(px(tx0 + colw), px(ty0 + 6)), (px(tx0 + colw), px(ty0 + 46))], fill=(200, 230, 201, 255), width=px(3))
    d.line([(px(tx0 + 2 * colw), px(ty0 + 6)), (px(tx0 + 2 * colw), px(ty0 + 46))], fill=(200, 230, 201, 255), width=px(3))

    return img.resize((N, N), Image.LANCZOS)


if __name__ == "__main__":
    logo = build()
    logo.save(os.path.join(HERE, "logo.png"))
    logo.save(
        os.path.join(HERE, "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("logo.png, icon.ico записано")
