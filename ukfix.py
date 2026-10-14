"""
Виправлення українських літер після розпізнавання за словником: OCR плутає «і» з «и», «є» з «е», «ї» з «і»
('ФИЗИЧНА' замість 'ФІЗИЧНА'). Слово, якого немає в українському словнику, замінюється варіантом із
такою самою заміною літер - лише коли такий варіант у словнику рівно один. Працює тільки для документів
з українськими літерами в тексті (щоб не «українізувати» російські документи); коди, артикули, латиниця
й короткі абревіатури не чіпаються. Без пакета pymorphy3 нічого не робить.
"""
import collections
import itertools
import re

_PAIRS = (("и", "і"), ("е", "є"), ("і", "ї"), ("і", "и"), ("ї", "і"), ("є", "е"), ("ґ", "г"), ("г", "ґ"),
          ("э", "є"), ("ы", "и"), ("п", "л"), ("л", "п"))
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


def _case_like(word, fixed):
    if word.isupper():
        return fixed.upper()
    if word[0].isupper():
        return fixed[0].upper() + fixed[1:]
    return fixed


def _mixed_case(word):
    """Слово з трьома й більше групами великих літер ('УкРАїНИ'): це OCR, а не марка на кшталт 'ЕкоСвіт'."""
    return len(re.findall(r"[А-ЯІЇЄҐ]+", word)) >= 3 and any(ch.islower() for ch in word)


def fix_word(word):
    """Виправлене слово або те саме, якщо виправляти нічого або неоднозначно."""
    if len(word) >= MIN_LENGTH and _mixed_case(word):
        upper_share = sum(1 for ch in word if ch.isupper()) / len(word)
        word = word.upper() if upper_share > 0.5 else word.lower().capitalize()
    if len(word) < MIN_LENGTH or (word.isupper() and len(word) <= MAX_ABBREVIATION) or is_known(word):
        return word
    low = word.lower()
    for edits in (1, 2):
        good = [v for v in _variants(low, edits) if is_known(v)]
        if len(good) == 1:
            return _case_like(word, good[0])
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
        before = text[match.start() - 1] if match.start() else ""
        new = match.group(0) if before and before in "\"'«“„" else fix_word(match.group(0))
        if new != match.group(0):
            changes.append((match.group(0), new))
        return new

    return _RUN.sub(sub, text), changes


def consensus_words(words, min_length=6, rare=2, common=4):
    """Рідкісне слово, що відрізняється однією літерою від слова, яке в цьому ж документі трапляється значно частіше
    ('попімерпіщаний' поряд із 12 'полімерпіщаний'), замінюється частим: так виправляються помилки OCR у назвах,
    яких немає в словнику. Повертає (слова, [(було, стало)])."""
    counts = collections.Counter(
        m.group(0).lower() for w in words for m in _RUN.finditer(w["text"]) if len(m.group(0)) >= min_length
    )
    frequent = [t for t, n in counts.items() if n >= common]
    if not frequent:
        return words, []
    changes = []

    def replacement(token):
        low = token.lower()
        if len(token) < min_length or counts[low] > rare:
            return token
        near = [u for u in frequent if len(u) == len(low) and u != low and counts[u] >= max(common, 3 * counts[low])
                and sum(a != b for a, b in zip(low, u)) <= (2 if len(low) >= 10 else 1)]
        if len(near) != 1:
            return token
        return _case_like(token, near[0])

    result = []
    for w in words:
        def sub(match):
            new = replacement(match.group(0))
            if new != match.group(0):
                changes.append((match.group(0), new))
            return new

        text = _RUN.sub(sub, w["text"])
        result.append(dict(w, text=text) if text != w["text"] else w)
    return result, changes


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
    result, voted = consensus_words(result)
    return result, changes + voted
