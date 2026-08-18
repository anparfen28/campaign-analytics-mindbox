#!/usr/bin/env python3
"""Чтение доски Trello. Только списки «Готово». Только GET.

Двухуровневая схема — она же причина, по которой это быстро:
  index  — лёгкий список карточек без комментариев, кэшируется (~6 сек, потом 0)
  card   — комментарии ОДНОЙ карточки по требованию (~1 сек)

Выкачивать доску целиком не надо: это ~150 запросов и минуты вместо секунд.

    python3 trello.py index [--refresh]
    python3 trello.py card <cardId|shortUrl|дд.мм>
    python3 trello.py find <дд.мм.гггг>
"""
import json
import os
import sys

import common

INDEX_PATH = os.path.join(common.KNOWLEDGE, "trello_index.json")


# Стадии доски по порядку. Нужны, чтобы понимать, где кампания находится СЕЙЧАС:
# планируется, готовится, идёт или завершена. Без этого разбор кампании, которая
# ещё не стартовала, выглядит так же уверенно, как разбор завершённой.
STAGE_ORDER = {
    "Входящие": 0, "Бэклог": 1, "Roadmap": 2, "Подготовка": 3,
    "Креативы и тексты": 4, "Запуск": 5, "Пострелиз": 6, "Аналитика": 7,
    "В рекламе постоянно": 8, "Готово": 9,
}


def stage_of(list_name):
    for key, rank in STAGE_ORDER.items():
        if list_name.startswith(key):
            return rank, key
    return -1, list_name


def build_index(refresh=False, done_only=True):
    """Индекс карточек.

    По умолчанию отдаём только «Готово» — знания о кампаниях живут там.
    Но в файл кладём ВСЮ доску: чтобы ответить «на какой стадии кампания»,
    надо видеть и «Подготовку», и «Запуск». Имена и даты стоят дёшево,
    комментарии оттуда всё равно не читаем.
    """
    if not refresh and os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, encoding="utf-8") as f:
            index = json.load(f)
    else:
        cfg = common.config()
        bid = cfg["trello_board_id"]
        lists = {l["id"]: l["name"] for l in
                 common.trello_get("/boards/%s/lists" % bid, fields="name")}
        # кастомные поля дают график промо: план/факт запуска, готовность
        # контента и дизайна, окончание — это и есть положение во времени
        fields = {f["id"]: f.get("name") for f in
                  common.trello_get("/boards/%s/customFields" % bid)}
        cards = common.trello_get(
            "/boards/%s/cards" % bid,
            fields="name,idList,shortUrl,dateLastActivity,desc,due",
            customFieldItems="true", limit=1000,
        )
        index = []
        for c in cards:
            list_name = lists.get(c["idList"], "")
            rank, stage = stage_of(list_name)
            dates = {}
            for item in c.get("customFieldItems", []) or []:
                name = fields.get(item.get("idCustomField"))
                val = (item.get("value") or {}).get("date")
                if name and val:
                    dates[name] = val[:10]
            index.append({
                "id": c["id"], "name": c["name"], "list": list_name,
                "stage": stage, "stage_rank": rank,
                "is_done": list_name.startswith("Готово"),
                "url": c["shortUrl"], "last_activity": c.get("dateLastActivity"),
                "due": (c.get("due") or "")[:10],
                "promo_dates": dates,
                "desc": c.get("desc", ""),
                "dates": sorted(common.dates_in_name(c["name"])),
                "months": sorted(common.months_in_name(c["name"])),
            })
        common.ensure_knowledge()
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)

    return [c for c in index if c.get("is_done")] if done_only else index


def get_comments(card_id):
    """Комментарии одной карточки, старые первыми, с очисткой."""
    acts = common.trello_get(
        "/cards/%s/actions" % card_id, filter="commentCard", limit=1000
    )
    out = []
    for a in reversed(acts):
        cleaned = common.clean_comment(a["data"]["text"])
        out.append({
            "date": a["date"][:10],
            "author": (a.get("memberCreator") or {}).get("fullName"),
            "raw": a["data"]["text"],
            **cleaned,
        })
    return out


def find_by_date(index, day, month):
    hits = [c for c in index if [day, month] in [list(d) for d in c["dates"]]]
    if hits:
        return hits, "день+месяц"
    hits = [c for c in index if month in c["months"]]
    return hits, "только месяц (менее надёжно)"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]

    if cmd == "index":
        idx = build_index(refresh="--refresh" in args)
        print("Карточек в «Готово»: %d" % len(idx))
        for c in sorted(idx, key=lambda x: x["name"]):
            ds = " ".join("%02d.%02d" % (d, m) for d, m in c["dates"]) or "—"
            print("  [%-12s] %-58s %s  %s" % (c["list"], c["name"][:58], ds, c["url"]))
        return 0

    if cmd == "stages":
        # Где кампании находятся ПРЯМО СЕЙЧАС. Комментарии не читаем — только
        # положение на доске и даты промо из кастомных полей.
        import datetime
        today = datetime.date.today().isoformat()
        idx = build_index(refresh="--refresh" in args, done_only=False)
        positional = [a for a in args[1:] if not a.startswith("--")]
        query = positional[0].lower() if positional else None
        rows = [c for c in idx if not query or query in c["name"].lower()]
        rows.sort(key=lambda c: (c["stage_rank"], c["name"]))
        print("СЕГОДНЯ: %s\n" % today)
        cur = None
        for c in rows:
            if c["list"] != cur:
                cur = c["list"]
                done = " ← знания читаем отсюда" if c["is_done"] else ""
                print("\n%s%s" % (cur, done))
            d = c["promo_dates"]
            when = " · ".join("%s %s" % (k.replace("Запуск промо ", "запуск "), v)
                              for k, v in sorted(d.items())) or "дат нет"
            print("  %-56s %s" % (c["name"][:56], when))
        print("\nКампания вне «Готово» ещё не завершена: результатов нет и быть не может.")
        return 0

    if cmd == "find":
        if len(args) < 2:
            print("нужна дата вида 22.07.2026")
            return 1
        parts = args[1].split(".")
        idx = build_index()
        hits, how = find_by_date(idx, int(parts[0]), int(parts[1]))
        print("Поиск по дате %s — совпадение: %s" % (args[1], how))
        for c in hits:
            print("  %-58s %s" % (c["name"][:58], c["url"]))
        if not hits:
            print("  ничего не найдено — карточки может не быть на доске")
        return 0

    if cmd == "card":
        if len(args) < 2:
            print("нужен id карточки, shortUrl или дата дд.мм")
            return 1
        key = args[1]
        idx = build_index()
        card = None
        if "." in key and len(key.split(".")) >= 2:
            p = key.split(".")
            hits, _ = find_by_date(idx, int(p[0]), int(p[1]))
            if len(hits) == 1:
                card = hits[0]
            elif len(hits) > 1:
                print("Несколько кандидатов — уточни:")
                for c in hits:
                    print("  %s  %s" % (c["name"], c["url"]))
                return 1
        if card is None:
            card = next((c for c in idx if key in (c["id"], c["url"])
                         or key.lower() in c["name"].lower()), None)
        if card is None:
            print("Карточка не найдена среди %d в «Готово»" % len(idx))
            return 1

        comments = get_comments(card["id"])
        print("КАРТОЧКА: %s" % card["name"])
        print("  список: %s · %s · комментариев: %d"
              % (card["list"], card["url"], len(comments)))
        links = sorted({l for c in comments for l in c["links"]})
        docs = [l for l in links if "docs.google.com" in l]
        if docs:
            print("\n  ССЫЛКИ НА ДОКУМЕНТЫ — по ним НАДО сходить (%d):" % len(docs))
            for l in sorted(set(docs)):
                print("    " + l[:150])
        print("\n--- КОММЕНТАРИИ ---")
        for c in comments:
            mark = " [@card]" if c["has_card"] else ""
            if c["empty_after_clean"]:
                mark += " [пусто после очистки: смысл в картинке/ссылке]"
            print("\n[%s] %s%s" % (c["date"], c["author"], mark))
            if c["quotes"]:
                print("  ЦИТИРУЕТ (ЧУЖИЕ слова, часто чтобы возразить):")
                for q in c["quotes"].split("\n")[:6]:
                    print("    > " + q[:160])
            for line in c["body"].split("\n"):
                if line.strip():
                    print("  " + line[:200])
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
