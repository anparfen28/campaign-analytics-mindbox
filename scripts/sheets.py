#!/usr/bin/env python3
"""Чтение обеих таблиц. Только чтение — функций записи здесь нет и быть не должно.

    python3 sheets.py svodnaya          — ивенты с воронкой (служебные строки отсеяны)
    python3 sheets.py tabs              — список вкладок медиапланов
    python3 sheets.py tab <gid>         — каналы одной кампании
    python3 sheets.py allchannels       — сводный слой «Все каналы»
"""
import json
import re
import sys

import common

# Реальный флайт — «Платные каналы» и прочие платные источники.
# «Резерв» и «Скипнули» — рассматривали, но НЕ купили: в расчёт кампании не входят.
# «Внутренний PR» — свои бесплатные каналы, денег не стоят.
#
# ВАЖНО: секцию менять ТОЛЬКО по распознанному заголовку. В «Резерве» много строк
# с одним-двумя заполненными полями (название канала и ссылка без цен), и если
# считать секцией любую малозаполненную строку, флайт «расширится» вчетверо —
# на Фоксфорде это давало 86 каналов и 2,67 млн ₽ вместо 27 и 966 тысяч.
SECTION_RE = re.compile(
    r"^\s*(платные\s+каналы|бюджет\s*[-–—]|внутренний\s+pr|резерв|скипнули|"
    r"посевы\s+через|бартер|бесплатн|итого)", re.I)
SKIP_SECTIONS = ("резерв", "скипнули", "внутренний pr")

# Внутри «Посевов через Яндекс Директ» лежит детализация с другой раскладкой:
# в колонке «Канал» стоит UTM-метка вида CPA|event|ev|Foxford|, а числа рядом —
# клики, а не деньги. Агрегат этих посевов и так есть отдельной строкой выше.
JUNK_LABEL_RE = re.compile(r"^\s*(итого|всего|[A-Z]{3}\s*\||.*\|\s*ev\s*\|)", re.I)


def _svodnaya_rows(gc, cfg):
    ws = gc.open_by_key(cfg["sheet_svodnaya"]).get_worksheet_by_id(cfg["gid_svodnaya"])
    values = ws.get_all_values()
    headers = [common.norm_header(h) for h in values[4]]  # шапка в строке 5
    out = []
    for row in values[5:]:
        name = (row[0] if row else "").strip()
        date = (row[1] if len(row) > 1 else "").strip()
        # ивент = имя есть И дата валидная. Иначе это служебная строка
        # («Среднее значение за 2026», «Для вебинаров:», заготовка без даты).
        if not name or not re.match(r"^\d{1,2}[./]\d{1,2}[./]\d{4}$", date):
            continue
        rec = {"event": name, "date": date}
        for i, h in enumerate(headers):
            if h and i < len(row) and i > 1:
                rec[h] = row[i]
        out.append(rec)
    return headers, out


def _fmt(value, digits=0):
    return format(value, ",.%df" % digits).replace(",", " ") if value is not None else "—"


def cmd_svodnaya(gc, cfg):
    _, rows = _svodnaya_rows(gc, cfg)
    print("ИВЕНТЫ В СВОДНОЙ: %d" % len(rows))
    print("%-44s %-11s %12s %7s %8s %8s %7s" % (
        "ивент", "дата", "бюджет", "рег", "CPA", "S+ рекл", "CTR"))
    for r in rows:
        print("%-44s %-11s %12s %7s %8s %8s %7s" % (
            r["event"][:43],
            r["date"],
            _fmt(common.num(r.get("Стоимость"))),
            _fmt(common.num(r.get("Регистрации с платной"))),
            _fmt(common.num(r.get("CPA"))),
            _fmt(common.num(r.get("S+ c рекламы"))),
            str(r.get("CTR", ""))[:6],
        ))
    print("\n⚠ Бенчмарки из ячеек со средними НЕ использовать — там подтверждённые")
    print("  ошибки. Считай через metrics.py benchmarks.")


def cmd_tabs(gc, cfg):
    sh = gc.open_by_key(cfg["sheet_posevy"])
    print("ВКЛАДКИ МЕДИАПЛАНОВ")
    for ws in sh.worksheets():
        title = ws.title.strip()
        kind = "кампания" if re.match(r"(Ивент|Контент|Кампании|Конференц)", title) else "служебная"
        print("  gid=%-12s %-52s %s" % (ws.id, title[:52], kind))


def read_tab(gc, cfg, gid):
    """Каналы реального флайта из вкладки кампании."""
    ws = gc.open_by_key(cfg["sheet_posevy"]).get_worksheet_by_id(int(gid))
    values = ws.get_all_values()
    headers = [common.norm_header(h) for h in values[0]]
    col = lambda *n: common.find_col(headers, *n)
    c = {
        "channel": col("Канал"), "link": col("Ссылка"),
        "cat": col("Категория канала"), "ca": col("ЦА"),
        "new": col("Новый канал да/нет"), "cost": col("Стоимость"),
        "plan": col("Регистрации (план)"), "fact": col("Регистрации (факт)"),
        "reach": col("Охват публикации"), "reach1": col("Охват 1 дня"),
        "aud": col("Объем аудитории"), "clicks": col("Переходы"),
        "ctr": col("CTR"), "cr": col("CR"), "cpv": col("CPV"),
        # На части вкладок есть И «S+» (план), И «S+ факт». Порядок важен:
        # без него в итог попадает план — на «Неделе удержания» это давало
        # 22 вместо 95, и ошибка тихая.
        "sp": col("S+ факт", "S+ (факт)", "S+"),
        "tsp": col("Целевые S+ факт", "Целевые S+ (факт)", "Целевые S+"),
        "last": col("Дата нашего последнего размещения"),
        "hypo": col("Гипотезы"),
    }
    rows, section = [], ""
    for row in values[1:]:
        if not any(x.strip() for x in row):
            continue
        label = (row[c["channel"]] if c["channel"] is not None and len(row) > c["channel"] else "").strip()
        filled = sum(1 for x in row if str(x).strip())
        if label and filled <= 4 and SECTION_RE.match(label):
            section = label            # только распознанный заголовок меняет секцию
            continue
        if not label or JUNK_LABEL_RE.match(label):
            continue
        if any(s in section.lower() for s in SKIP_SECTIONS):
            continue
        if common.num(row[c["cost"]] if c["cost"] is not None and len(row) > c["cost"] else None) is None:
            continue                   # без цены это не купленное размещение
        g = lambda k: common.num(row[c[k]]) if c[k] is not None and len(row) > c[k] else None
        t = lambda k: row[c[k]].strip() if c[k] is not None and len(row) > c[k] else ""
        rows.append({
            "section": section, "channel": label, "link": t("link"),
            "tme": common.tme(t("link")), "category": t("cat"), "audience": t("ca"),
            "is_new": t("new").lower().startswith(("да", "yes")),
            "cost": g("cost"), "plan": g("plan"), "fact": g("fact"),
            "reach": g("reach"), "reach_day1": g("reach1"), "audience_size": g("aud"),
            "clicks": g("clicks"), "ctr": g("ctr"), "cr": g("cr"), "cpv": g("cpv"),
            "sp": g("sp"), "target_sp": g("tsp"), "last_placement": t("last"),
            "hypothesis": t("hypo"),
        })
    # Дубли строк встречаются (на «Неделе удержания» Mailfit заведён дважды),
    # и без дедупликации бюджет и регистрации задваиваются.
    seen, unique = set(), []
    for r in rows:
        key = (r["tme"] or r["channel"].lower().strip(), r["cost"], r["fact"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return ws.title.strip(), unique


def cmd_tab(gc, cfg, gid):
    title, rows = read_tab(gc, cfg, gid)
    print("ВКЛАДКА: %s — каналов в флайте: %d" % (title, len(rows)))
    print(json.dumps(rows, ensure_ascii=False, indent=1))


def read_all_channels(gc, cfg):
    ws = gc.open_by_key(cfg["sheet_posevy"]).get_worksheet_by_id(cfg["gid_all_channels"])
    values = ws.get_all_values()
    headers = [common.norm_header(h) for h in values[0]]
    col = lambda *n: common.find_col(headers, *n)
    ix = {"year": col("Год"), "flight": col("Название флайта"),
          "kind": col("Ивент/Контент"), "adchan": col("Рекламный канал"),
          "channel": col("Канал"), "link": col("Ссылка"), "cost": col("Стоимость"),
          "clicks": col("Переходы"), "regs": col("Регистрации/отправка формы", "Регистрации"),
          "cpa": col("СРА", "CPA"), "cr": col("CR"), "sp": col("S+"),
          "reach": col("Охват"), "ctr": col("CTR")}
    out = []
    for row in values[1:]:
        if ix["channel"] is None or len(row) <= ix["channel"] or not row[ix["channel"]].strip():
            continue
        g = lambda k: common.num(row[ix[k]]) if ix[k] is not None and len(row) > ix[k] else None
        t = lambda k: row[ix[k]].strip() if ix[k] is not None and len(row) > ix[k] else ""
        out.append({"year": t("year"), "flight": t("flight"), "kind": t("kind"),
                    "ad_channel": t("adchan"), "channel": t("channel"),
                    "tme": common.tme(t("link")), "cost": g("cost"),
                    "clicks": g("clicks"), "regs": g("regs"), "cpa": g("cpa"),
                    "cr": g("cr"), "sp": g("sp"), "reach": g("reach"), "ctr": g("ctr")})
    return out


def cmd_allchannels(gc, cfg):
    rows = read_all_channels(gc, cfg)
    print("ВСЕ КАНАЛЫ: строк %d, площадок %d, флайтов %d" % (
        len(rows), len({r["channel"] for r in rows}), len({r["flight"] for r in rows})))
    print(json.dumps(rows[:20], ensure_ascii=False, indent=1))
    print("... (полный вывод используй из кода, не глазами)")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cfg = common.config()
    gc = common.gspread_client()
    cmd = args[0]
    if cmd == "svodnaya":
        cmd_svodnaya(gc, cfg)
    elif cmd == "tabs":
        cmd_tabs(gc, cfg)
    elif cmd == "tab":
        cmd_tab(gc, cfg, args[1])
    elif cmd == "allchannels":
        cmd_allchannels(gc, cfg)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
