#!/usr/bin/env python3
"""Время: когда выходить с постами и насколько цифры уже созрели.

Два разных вопроса, которые легко перепутать:

1. КОГДА ПУБЛИКОВАТЬ — эффект дня выхода относительно даты ивента. Считается
   по завершённым кампаниям, данных хватает.
2. НАСКОЛЬКО ЦИФРА ПОЛНАЯ — если пост вышел вчера, регистрации по нему ещё идут,
   и текущий факт занижен.

⚠️ Честное ограничение: посуточных срезов регистраций в источниках НЕТ, есть только
итоговое число на канал. Значит настоящую кривую накопления одного поста построить
не из чего. Всё, что можно, — оценить зрелость по тому, сколько окна промо прошло,
и по истории самого канала. Выдавать такую оценку за факт нельзя.

    python3 timing.py curve                 — когда выходить: эффект дня публикации
    python3 timing.py maturity <gid> <дата ивента дд.мм.гггг>
"""
import collections
import datetime
import re
import sys

import common
import sheets

BUCKETS = [(3, "0-3 дня"), (7, "4-7 дней"), (14, "8-14 дней"), (45, "15+ дней")]


def bucket(delta):
    for limit, name in BUCKETS:
        if delta <= limit:
            return name
    return None


def pub_dates(gc, cfg, gid):
    """Дата публикации по каждому каналу. В источнике формат «07.07» без года."""
    ws = gc.open_by_key(cfg["sheet_posevy"]).get_worksheet_by_id(int(gid))
    values = ws.get_all_values()
    headers = [common.norm_header(h) for h in values[0]]
    ic = common.find_col(headers, "Дата публикации")
    ich = common.find_col(headers, "Канал")
    out = {}
    if ic is None or ich is None:
        return out
    for row in values[1:]:
        if len(row) > max(ic, ich) and row[ich].strip():
            out[row[ich].strip()] = row[ic].strip()
    return out


def parse_pub(text, event_date):
    m = re.match(r"(\d{1,2})[.\-/](\d{1,2})", str(text))
    if not m:
        return None
    try:
        d = datetime.date(event_date.year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    # промо идёт до ивента; если дата «после», это прошлый год
    if (event_date - d).days < -30:
        d = d.replace(year=event_date.year - 1)
    return d


def cmd_curve(gc, cfg):
    _, svod = sheets._svodnaya_rows(gc, cfg)
    dates = {}
    for r in svod:
        try:
            dd, mm, yy = re.split(r"[./]", r["date"])
            dates[r["event"]] = datetime.date(int(yy), int(mm), int(dd))
        except ValueError:
            continue

    sh = gc.open_by_key(cfg["sheet_posevy"])
    agg = collections.defaultdict(lambda: [0.0, 0.0, 0])
    used = []
    for ws in sh.worksheets():
        title = ws.title.strip()
        if not title.lower().startswith(("ивент", "конференц")):
            continue
        ym = re.search(r"(20\d\d)", title)
        if not ym:
            continue
        year = int(ym.group(1))
        cand = [d for e, d in dates.items() if d.year == year]
        if not cand:
            continue
        try:
            _, rows = sheets.read_tab(gc, cfg, ws.id)
            pubs = pub_dates(gc, cfg, ws.id)
        except Exception:  # noqa: BLE001
            continue
        # дата ивента = максимум из дат публикации + несколько дней; надёжнее взять
        # ближайшую дату ивента того же года к последней публикации
        pd = [parse_pub(v, datetime.date(year, 12, 31)) for v in pubs.values()]
        pd = [p for p in pd if p]
        if not pd:
            continue
        last = max(pd)
        edate = min(cand, key=lambda d: abs((d - last).days))
        if abs((edate - last).days) > 30:
            continue
        n = 0
        for r in rows:
            p = parse_pub(pubs.get(r["channel"], ""), edate)
            if not p or not r["fact"]:
                continue
            delta = (edate - p).days
            if delta < 0 or delta > 45:
                continue
            b = bucket(delta)
            agg[b][0] += r["fact"]
            agg[b][1] += r["cost"] or 0
            agg[b][2] += 1
            n += 1
        if n:
            used.append((title, edate.isoformat(), n))

    print("КОГДА ВЫХОДИТЬ: эффект дня публикации относительно даты ивента\n")
    for t, d, n in used:
        print("  %-46s ивент %s · постов с датой %d" % (t[:45], d, n))
    print("\n%-12s %8s %13s %14s %10s" % ("до ивента", "постов", "регистраций", "бюджет", "CPA"))
    for _, name in BUCKETS:
        reg, cost, n = agg[name]
        if not n:
            continue
        print("%-12s %8d %13.0f %14s %10s" % (
            name, n, reg, format(cost, ",.0f").replace(",", " "),
            format(cost / reg, ",.0f").replace(",", " ") if reg else "—"))
    print("\nЧитать так: объём и цена — разные вещи. Последние дни перед ивентом обычно")
    print("дают больше всего регистраций, но не самый дешёвый CPA.")


def cmd_maturity(gc, cfg, gid, event_date_str):
    dd, mm, yy = re.split(r"[./]", event_date_str)
    edate = datetime.date(int(yy), int(mm), int(dd))
    today = datetime.date.today()
    _, rows = sheets.read_tab(gc, cfg, gid)
    pubs = pub_dates(gc, cfg, gid)

    print("ЗРЕЛОСТЬ ДАННЫХ на %s · ивент %s" % (today.isoformat(), edate.isoformat()))
    if today > edate:
        print("Ивент прошёл %d дн. назад." % (today - edate).days)
        print("⚠ Данные могут быть неполными: Intensa переносят результаты из BI руками.")
    else:
        print("До ивента %d дн. Кампания ИДЁТ — итоговых цифр не существует." % (edate - today).days)

    print("\n%-30s %-12s %7s %7s %s" % ("канал", "публикация", "план", "факт", "статус"))
    pending = 0
    for r in rows:
        p = parse_pub(pubs.get(r["channel"], ""), edate)
        if p is None:
            status = "даты нет"
        elif p > today:
            status = "ещё не вышел"
            pending += 1
        elif (today - p).days <= 3:
            status = "вышел %d дн. назад — регистрации ещё идут" % (today - p).days
            pending += 1
        else:
            status = "созрел"
        print("%-30s %-12s %7s %7s %s" % (
            r["channel"][:29], p.isoformat() if p else "—",
            "%.0f" % r["plan"] if r["plan"] else "—",
            "%.0f" % r["fact"] if r["fact"] is not None else "—", status))

    if pending:
        print("\n⚠ %d размещений ещё не дали окончательных цифр." % pending)
        print("  Посуточных срезов в источниках нет, поэтому точный прогноз построить")
        print("  не из чего. Ориентир — план по этим каналам и их история; говори")
        print("  «ожидается около», а не называй число как факт.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cfg = common.config()
    gc = common.gspread_client()
    if args[0] == "curve":
        cmd_curve(gc, cfg)
    elif args[0] == "maturity" and len(args) >= 3:
        cmd_maturity(gc, cfg, args[1], args[2])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
