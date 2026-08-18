#!/usr/bin/env python3
"""Сшивка трёх источников по одному ивенту.

Название НЕ является ключом: совпадает 1 раз из 7. Ключ — дата, доказательство —
числовой отпечаток. Подробности и разбор ошибок — references/03_mapping.md.

    python3 link.py "Вебинар Фоксфорд"
    python3 link.py --all
"""
import json
import os
import re
import sys

import common
import sheets
import trello

EVENTS_PATH = os.path.join(common.KNOWLEDGE, "events.jsonl")


def tab_totals(gc, cfg, gid):
    """Эталонные числа кампании из вкладки медиаплана."""
    title, rows = sheets.read_tab(gc, cfg, gid)
    fact = sum(r["fact"] or 0 for r in rows)
    plan = sum(r["plan"] or 0 for r in rows)
    cost = sum(r["cost"] or 0 for r in rows)
    tsp = sum(r["target_sp"] or 0 for r in rows)
    return {"tab": title, "gid": gid, "fact": fact, "plan": plan,
            "cost": cost, "target_sp": tsp, "channels": len(rows)}


def match_tab_to_flight(tab_rows, all_channels, year):
    """Вкладка ↔ флайт по ДОЛЕ каналов флайта, найденных во вкладке.

    Не по Жаккару: у верного ответа он всего 0.31 и не отличим уверенно.
    Фильтр по году обязателен, иначе Фоксфорд-2025 склеится с Foxford-2026.
    """
    tabset = {r["tme"] for r in tab_rows if r["tme"]}
    flights = {}
    for r in all_channels:
        if year and r["year"] != str(year):
            continue
        if r["tme"]:
            flights.setdefault(r["flight"], set()).add(r["tme"])
    scored = []
    for name, chans in flights.items():
        if not chans:
            continue
        covered = len(tabset & chans) / len(chans)
        scored.append((covered, len(tabset & chans), len(chans), name))
    scored.sort(reverse=True)
    return scored


def fingerprint(comments, refs):
    """Сверка эталонных чисел с числами в комментариях.

    Эталоны — только те числа, которые люди произносят вслух. Проценты с допуском ±1
    (округляют по-разному), суммы ±1%. Иначе правильная связка отвергается — так
    и произошло на первой версии с «планом 462» и «73% вместо 72».
    """
    pool = set()
    for c in comments:
        pool |= common.numbers_in_prose(c["raw"])
    hits = []
    for label, value, kind in refs:
        if not value:
            continue
        tol = 1 if kind == "pct" else max(1.0, value * 0.01)
        ok = any(abs(n - value) <= tol for n in pool)
        hits.append((label, value, ok))
    return hits


def link_event(gc, cfg, event_name, index=None, svod=None, allch=None):
    cfg = cfg or common.config()
    index = index if index is not None else trello.build_index()
    if svod is None:
        _, svod = sheets._svodnaya_rows(gc, cfg)
    if allch is None:
        allch = sheets.read_all_channels(gc, cfg)

    row = next((r for r in svod if event_name.lower() in r["event"].lower()), None)
    if row is None:
        return {"event": event_name, "error": "нет такого ивента в сводной"}

    d, m, y = re.split(r"[./]", row["date"])
    d, m, y = int(d), int(m), int(y)

    # ── вкладка медиаплана.
    # Названия вкладок содержат месяц и год («Ивент Foxford - июль 2026»), поэтому
    # кандидатов отбираем по заголовкам — они приходят одним запросом метаданных.
    # Читать все 27 вкладок целиком нельзя: это десятки тяжёлых запросов и таймаут.
    sh = gc.open_by_key(cfg["sheet_posevy"])
    # Месяц ищем по границе слова и полной форме. Наивное вхождение подстроки
    # ломается на мае: обрубок «ма» находится внутри «Марио Берлучи февраль»,
    # и майский ивент тихо сшивается с февральской вкладкой.
    month_pat = [r"январ", r"феврал", r"март", r"апрел", r"ма[йя]", r"июн",
                 r"июл", r"август", r"сентябр", r"октябр", r"ноябр", r"декабр"]
    pat = re.compile(r"\b" + month_pat[m - 1])
    titles = [(ws.id, ws.title.strip()) for ws in sh.worksheets()]

    def plausible(title):
        low = title.lower()
        if not re.match(r"(ивент|конференц|кампании)", low):
            return False          # ивенты сшиваем с ивентовыми вкладками
        if str(y) not in title and str(y)[2:] not in title:
            return False
        return bool(pat.search(low))

    cands = [(gid, t) for gid, t in titles if plausible(t)]
    if not cands:                  # запасной вариант — только год
        cands = [(gid, t) for gid, t in titles
                 if re.match(r"(ивент|конференц|кампании)", t.lower())
                 and (str(y) in t or str(y)[2:] in t)]

    best_tab, best_score = None, 0.0
    for gid, t in cands[:6]:       # жёсткий потолок, чтобы не упереться в таймаут
        try:
            _, rows = sheets.read_tab(gc, cfg, gid)
        except Exception:  # noqa: BLE001
            continue
        scored = match_tab_to_flight(rows, allch, y)
        cover = scored[0][0] if scored else 0.0
        if cover >= best_score:
            best_score = cover
            best_tab = (gid, t, rows, scored[0] if scored else (0, 0, 0, "—"))

    result = {"event": row["event"], "date": row["date"]}
    if best_tab:
        gid, title, rows, top = best_tab
        result["tab"] = {"gid": gid, "title": title}
        result["flight"] = {"name": top[3], "coverage": round(top[0], 2),
                            "matched": top[1], "of": top[2]}
        # Телеграм-посевы считаем отдельно: Intensa в разборах оперируют именно
        # ими («335 регистраций»), а сводная — всем платным трафиком («357»).
        # Оба числа верны, и оба нужны как эталоны.
        tg = [r for r in rows if r["tme"]]
        totals = {"fact": sum(r["fact"] or 0 for r in rows),
                  "plan": sum(r["plan"] or 0 for r in rows),
                  "cost": sum(r["cost"] or 0 for r in rows),
                  "fact_tg": sum(r["fact"] or 0 for r in tg),
                  "plan_tg": sum(r["plan"] or 0 for r in tg),
                  "cost_tg": sum(r["cost"] or 0 for r in tg),
                  "target_sp": sum(r["target_sp"] or 0 for r in rows)}
        result["tab_totals"] = totals
    else:
        totals = {}

    # ── карточка Trello: кандидат по дате среди «Готово»
    cands, how = trello.find_by_date(index, d, m)
    result["date_match"] = how
    scored_cards = []
    for c in cands:
        comments = trello.get_comments(c["id"])
        # Эталоны — только те числа, которые люди произносят вслух.
        # Внутренние агрегаты вроде «плана по каналам» не цитируют никогда.
        refs = [
            ("регистрации, посевы", totals.get("fact_tg"), "abs"),
            ("регистрации, весь платный", totals.get("fact"), "abs"),
            ("регистрации (сводная)", common.num(row.get("Регистрации с платной")), "abs"),
            ("бюджет (сводная)", common.num(row.get("Стоимость")), "abs"),
            ("целевых S+ (вкладка)", totals.get("target_sp"), "abs"),
        ]
        for label, f, p in (("выполнение, посевы, %", totals.get("fact_tg"), totals.get("plan_tg")),
                            ("выполнение, весь флайт, %", totals.get("fact"), totals.get("plan"))):
            if f and p:
                refs.append((label, round(f / p * 100), "pct"))
        hits = fingerprint(comments, refs)
        n_ok = sum(1 for _, _, ok in hits if ok)
        scored_cards.append((n_ok, c, hits, len(comments)))
    scored_cards.sort(key=lambda x: -x[0])

    if scored_cards:
        n_ok, c, hits, ncom = scored_cards[0]
        result["trello"] = {"name": c["name"], "url": c["url"], "list": c["list"],
                            "comments": ncom}
        result["fingerprint"] = [{"ref": l, "value": v, "found": ok} for l, v, ok in hits]
        result["confidence"] = ("подтверждено" if n_ok >= 2
                                else "вероятно" if n_ok == 1 else "НЕ ПОДТВЕРЖДЕНО")
        if n_ok == 0:
            result["warning"] = ("числа не сошлись — связывать нельзя, "
                                 "покажи человеку")
        names = {row["event"].lower(), c["name"].lower()}
        if result.get("tab"):
            names.add(result["tab"]["title"].lower())
        result["name_mismatch"] = len(names) > 1
    else:
        result["trello"] = None
        result["warning"] = "карточка не найдена в списках «Готово»"
    return result


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cfg = common.config()
    gc = common.gspread_client()
    index = trello.build_index()
    _, svod = sheets._svodnaya_rows(gc, cfg)
    allch = sheets.read_all_channels(gc, cfg)

    targets = [r["event"] for r in svod] if args[0] == "--all" else [args[0]]
    out = []
    for name in targets:
        res = link_event(gc, cfg, name, index, svod, allch)
        out.append(res)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        print("-" * 70)

    # Накопленное не затирать: файл открывается на чтение, связки сливаются
    # по ключу «ивент + дата», и только потом переписывается целиком.
    common.ensure_knowledge()
    store = {}
    if os.path.exists(EVENTS_PATH):
        with open(EVENTS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    store[(rec.get("event"), rec.get("date"))] = rec
                except json.JSONDecodeError:
                    continue
    added = 0
    for r in out:
        if r.get("trello"):
            key = (r.get("event"), r.get("date"))
            if key not in store:
                added += 1
            store[key] = r
    with open(EVENTS_PATH, "w", encoding="utf-8") as f:
        for rec in store.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("связок в knowledge/events.jsonl: %d (новых %d)" % (len(store), added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
