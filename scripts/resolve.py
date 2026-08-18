#!/usr/bin/env python3
"""Нечёткое сопоставление того, как ивент называет человек, с тем, как он записан.

Люди говорят «Фокс», «вебинар Фоксфорд», «тот с Яндексом», «июньский ивент».
В источниках он записан иначе, и по-разному в каждом из трёх. Этот модуль
принимает произвольную формулировку и возвращает кандидатов из сводной таблицы.

Ищем сразу по нескольким полям, потому что публичное название ивента может
не встречаться в сводной вовсе: «Реклама по расчету» = карточка «Промо: ивента
с Яндексом 25.02», и связь видна только через дату или текст комментария.

    python3 resolve.py "фоксфорд"
    python3 resolve.py "июньский ивент"
"""
import difflib
import re
import sys

import common
import sheets
import trello

# Латиница ⇄ кириллица: «Mario Berlucci» в сводной и «Марио Берлучи» в Trello.
TRANSLIT = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
    "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "у", "z": "з",
}

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}


def fold(text):
    """Схлопывает регистр, латиницу, ё и всё небуквенное — для сравнения."""
    s = str(text).lower().replace("ё", "е")
    s = "".join(TRANSLIT.get(ch, ch) for ch in s)
    return re.sub(r"[^а-я0-9]+", "", s)


def score(query, target):
    """0..1. Учитывает вхождение подстроки — «фокс» внутри «фоксфорд»."""
    q, t = fold(query), fold(target)
    if not q or not t:
        return 0.0
    if q in t or t in q:
        return 0.92 + 0.08 * (min(len(q), len(t)) / max(len(q), len(t)))
    return difflib.SequenceMatcher(None, q, t).ratio()


def month_in(query):
    low = str(query).lower()
    for stem, m in MONTHS.items():
        if re.search(r"\b" + stem, low):
            return m
    return None


def resolve(query, svod, index=None):
    """Кандидаты-ивенты, отсортированные по уверенности."""
    month = month_in(query)
    year = None
    ym = re.search(r"\b(20\d\d)\b", str(query))
    if ym:
        year = ym.group(1)

    index = index if index is not None else []
    # текст карточек Trello — второй источник имён: публичное название ивента
    # часто лежит только там (в desc или даже в комментарии)
    card_text = {}
    for c in index:
        card_text[c["name"]] = (c["name"] + " " + (c.get("desc") or ""))[:4000]

    out = []
    for row in svod:
        s = score(query, row["event"])
        why = ["имя в сводной"] if s > 0.6 else []

        d, m, y = (re.split(r"[./]", row["date"]) + ["", "", ""])[:3]
        if month and int(m or 0) == month:
            s = max(s, 0.72)
            why.append("месяц")
        if year and y == year:
            s += 0.05
            why.append("год")

        # совпадение с текстом карточки Trello того же месяца
        for name, text in card_text.items():
            if fold(query) and fold(query) in fold(text):
                dates = common.dates_in_name(name)
                if any(mm == int(m or 0) for _, mm in dates):
                    s = max(s, 0.85)
                    why.append("текст карточки «%s»" % name[:40])
                    break

        if s > 0.55:
            out.append({"event": row["event"], "date": row["date"],
                        "score": round(min(s, 1.0), 2), "why": why})
    out.sort(key=lambda x: -x["score"])
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    query = " ".join(sys.argv[1:])
    cfg = common.config()
    gc = common.gspread_client()
    _, svod = sheets._svodnaya_rows(gc, cfg)
    try:
        index = trello.build_index()
    except Exception:  # noqa: BLE001
        index = []

    hits = resolve(query, svod, index)
    print('ЗАПРОС: «%s»' % query)
    if not hits:
        print("  Ничего похожего среди %d ивентов сводной." % len(svod))
        print("  Не угадывай — покажи список ивентов и попроси уточнить.")
        return 0
    if len(hits) > 1 and hits[0]["score"] - hits[1]["score"] < 0.08:
        print("  ⚠ Несколько близких вариантов — уточни у человека, не выбирай сам.")
    for h in hits[:6]:
        print("  %.2f  %-46s %-11s  %s"
              % (h["score"], h["event"][:45], h["date"], ", ".join(h["why"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
