"""
Виправлення українських літер після розпізнавання за словником: OCR плутає «і» з «и», «є» з «е», «ї» з «і»
('ФИЗИЧНА' замість 'ФІЗИЧНА'). Слово, якого немає в українському словнику, замінюється варіантом із
такою самою заміною літер - лише коли такий варіант у словнику рівно один. Працює тільки для документів
з українськими літерами в тексті (щоб не «українізувати» російські документи); коди, артикули, латиниця
й короткі абревіатури не чіпаються. Без пакета pymorphy3 нічого не робить.
"""
import itertools
import re

_PAIRS = (("и", "і"), ("е", "є"), ("і", "ї"), ("і", "и"), ("ї", "і"), ("є", "е"), ("ґ", "г"), ("г", "ґ"),
          ("э", "є"), ("ы", "и"))
_RUN = re.compile(r"[А-Яа-яІіЇїЄєҐґЫыЭэ]+")
_UKRAINIAN_LETTERS = re.compile(r"[іїєґІЇЄҐ]")
MIN_UKRAINIAN_LETTERS = 5  # стільки українських літер у тексті, щоб вважати документ українським
MIN_LENGTH = 4
MAX_ABBREVIATION = 6  # слова великими літерами такої довжини й коротші - абревіатури або назви: не чіпаємо

_morph = None
_unavailable = False


def _dictionary():
    global _morph, _unavailable
    if _morph is None and not _unavailable:
        try:
            import pymorphy3

            _morph = pymorphy3.MorphAnalyzer(lang="uk")
        except Exception:
            _unavailable = True
    return _morph


def available():
    return _dictionary() is not None


def is_known(word):
    morph = _dictionary()
    return bool(morph and morph.word_is_known(word.lower()))


def _variants(low, edits):
    positions = [i for i, ch in enumerate(low) if any(ch == a for a, _ in _PAIRS)]
    found = set()
    for combo in itertools.combinations(positions, edits):
        options = [[(i, b) for a, b in _PAIRS if a == low[i]] for i in combo]
        for choice in itertools.product(*options):
            chars = list(low)
            for i, b in choice:
                chars[i] = b
            found.add("".join(chars))
    found.discard(low)
    return found


def fix_word(word):
    """Виправлене слово або те саме, якщо виправляти нічого або неоднозначно."""
    if len(word) < MIN_LENGTH or (word.isupper() and len(word) <= MAX_ABBREVIATION) or is_known(word):
        return word
    low = word.lower()
    for edits in (1, 2):
        good = [v for v in _variants(low, edits) if is_known(v)]
        if len(good) == 1:
            fixed = good[0]
            if word.isupper():
                return fixed.upper()
            if word[0].isupper():
                return fixed[0].upper() + fixed[1:]
            return fixed
        if good:
            return word  # кілька варіантів - не вгадуємо
    # OCR часто губить першу велику «І» ('нформаційні' -> 'Інформаційні')
    if len(word) >= 6 and word[0].islower() and is_known("і" + low):
        return "І" + word
    return word


def fix_text(text):
    """(виправлений текст, [(було, стало)])."""
    changes = []

    def sub(match):
        new = fix_word(match.group(0))
        if new != match.group(0):
            changes.append((match.group(0), new))
        return new

    return _RUN.sub(sub, text), changes


def is_ukrainian(texts):
    return sum(len(_UKRAINIAN_LETTERS.findall(t)) for t in texts) >= MIN_UKRAINIAN_LETTERS


def fix_words(words):
    """Слова OCR ({'text', ...}) із виправленими українськими літерами: (слова, [(було, стало)])."""
    if not words or not available() or not is_ukrainian(w["text"] for w in words):
        return words, []
    changes, result = [], []
    for w in words:
        text, done = fix_text(w["text"])
        changes += done
        result.append(dict(w, text=text) if done else w)
    return result, changes
