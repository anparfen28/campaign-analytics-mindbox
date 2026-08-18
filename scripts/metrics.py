#!/usr/bin/env python3
"""Вся арифметика. Ни одна цифра в ответе не должна появляться мимо этого файла.

    python3 metrics.py channels <gid> [--goal quality|volume|reach]
    python3 metrics.py history "<канал>"
    python3 metrics.py benchmarks
    python3 metrics.py budget --target-sp 50 [--like "<ивент>"]
"""
import argparse
import collections
import re
import sys

import common
import sheets

GOALS = {
    "quality": ("цена целевого S+", lambda r: r["cost_per_target_sp"]),
    "volume":  ("CPA",              lambda r: r["cpa"]),
    "reach":   ("CPV",              lambda r: r["cpv"]),
}


def enrich(rows):
    """Производные метрики. Считаем сами, а не читаем из ячеек: в таблице
    встречаются вбитые руками константы вместо формул."""
    for r in rows:
        cost, fact, tsp = r.get("cost"), r.get("fact"), r.get("target_sp")
        r["cpa"] = cost / fact if cost and fact else None
        r["cost_per_target_sp"] = cost / tsp if cost and tsp else None
        r["target_share"] = tsp / fact * 100 if fact and tsp else 0.0
        r["plan_pct"] = r["fact"] / r["plan"] * 100 if r.get("plan") and r.get("fact") else None
        if not r.get("cpv") and cost and r.get("reach_day1"):
            r["cpv"] = cost / r["reach_day1"]
    return rows


def cmd_channels(gc, cfg, gid, goal):
    title, rows = sheets.read_tab(gc, cfg, gid)
    rows = enrich(rows)
    label, key = GOALS[goal]

    budget = sum(r["cost"] or 0 for r in rows)
    fact = sum(r["fact"] or 0 for r in rows)
    plan = sum(r["plan"] or 0 for r in rows)
    tsp = sum(r["target_sp"] or 0 for r in rows)

    print("КАМПАНИЯ: %s" % title)
    print("  каналов %d · бюджет %s ₽ · регистраций %d (план %d, %s) · целевых S+ %d"
          % (len(rows), format(budget, ",.0f").replace(",", " "), fact, plan,
             ("%.0f%%" % (fact / plan * 100)) if plan else "—", tsp))
    if tsp:
        print("  средняя цена целевого S+: %s ₽" % format(budget / tsp, ",.0f").replace(",", " "))
    print("  ранжирование по цели «%s» → %s\n" % (goal, label))

    print("%-30s %10s %5s %7s %9s %7s %11s %7s %s"
          % ("канал", "бюджет", "рег", "%плана", "CPA", "цел.S+", "₽/целевой", "доля", "нов"))
    ranked = sorted(rows, key=lambda r: (key(r) is None, key(r) or 0))
    for r in ranked:
        print("%-30s %10s %5s %6s%% %9s %7s %11s %6.0f%% %s" % (
            r["channel"][:29],
            format(r["cost"], ",.0f").replace(",", " ") if r["cost"] else "—",
            "%.0f" % r["fact"] if r["fact"] is not None else "—",
            "%.0f" % r["plan_pct"] if r["plan_pct"] else "—",
            "%.0f" % r["cpa"] if r["cpa"] else ("нет рег" if r["fact"] == 0 else "—"),
            "%.0f" % r["target_sp"] if r["target_sp"] is not None else "—",
            format(r["cost_per_target_sp"], ",.0f").replace(",", " ")
            if r["cost_per_target_sp"] else "— нет",
            r["target_share"],
            "да" if r["is_new"] else "",
        ))

    new = [r for r in rows if r["is_new"]]
    if new:
        nb = sum(r["cost"] or 0 for r in new)
        nt = sum(r["target_sp"] or 0 for r in new)
        print("\nНОВЫЕ КАНАЛЫ: %d шт · %s ₽ (%.0f%% бюджета) · целевых S+ %d (%.0f%% от всех)"
              % (len(new), format(nb, ",.0f").replace(",", " "),
                 nb / budget * 100 if budget else 0, nt, nt / tsp * 100 if tsp else 0))


def cmd_history(gc, cfg, channel):
    rows = sheets.read_all_channels(gc, cfg)
    hits = [r for r in rows if channel.lower() in (r["channel"] or "").lower()]
    if not hits:
        print("Нет истории по «%s» — в своде такой площадки не встречалось." % channel)
        return
    print("ИСТОРИЯ ПЛОЩАДКИ: %s — размещений %d" % (channel, len(hits)))
    print("%-5s %-34s %11s %6s %9s %9s %5s" % ("год", "флайт", "бюджет", "рег", "CPA", "охват", "S+"))
    for r in sorted(hits, key=lambda x: (x["year"], x["flight"])):
        cpa = r["cpa"] or (r["cost"] / r["regs"] if r["cost"] and r["regs"] else None)
        print("%-5s %-34s %11s %6s %9s %9s %5s" % (
            r["year"], (r["flight"] or "")[:33],
            format(r["cost"], ",.0f").replace(",", " ") if r["cost"] else "—",
            "%.0f" % r["regs"] if r["regs"] is not None else "—",
            format(cpa, ",.0f").replace(",", " ") if cpa else "—",
            format(r["reach"], ",.0f").replace(",", " ") if r["reach"] else "—",
            "%.0f" % r["sp"] if r["sp"] is not None else "—"))
    by_year = collections.defaultdict(list)
    for r in hits:
        cpa = r["cpa"] or (r["cost"] / r["regs"] if r["cost"] and r["regs"] else None)
        if cpa:
            by_year[r["year"]].append(cpa)
    if len(by_year) > 1:
        print("\nдинамика CPA по годам:")
        for y in sorted(by_year):
            v = by_year[y]
            print("  %s: медиана %s ₽ (размещений %d)"
                  % (y, format(sorted(v)[len(v) // 2], ",.0f").replace(",", " "), len(v)))


def cmd_benchmarks(gc, cfg):
    """Пересчёт из строк ивентов. Ячейки со средними в таблице испорчены:
    CPA «AI в маркетинге» вбит константой, «среднее за 2026» считает 3 ивента из 7,
    «вебинары 2025» включают два ивента 2024 года."""
    _, rows = sheets._svodnaya_rows(gc, cfg)
    by_year = collections.defaultdict(list)
    for r in rows:
        year = re.split(r"[./]", r["date"])[-1]
        cost = common.num(r.get("Стоимость"))
        regs = common.num(r.get("Регистрации с платной"))
        sp = common.num(r.get("S+ c рекламы"))
        if cost and regs:
            by_year[year].append({"event": r["event"], "cpa": cost / regs,
                                  "cost": cost, "regs": regs, "sp": sp,
                                  "cps": cost / sp if sp else None})
    print("БЕНЧМАРКИ, ПЕРЕСЧИТАННЫЕ ИЗ СТРОК (ячейкам со средними не доверять)\n")
    print("%-6s %8s %12s %12s %14s" % ("год", "ивентов", "медиана CPA", "средний CPA", "медиана ₽/S+"))
    for y in sorted(by_year):
        v = by_year[y]
        cpas = sorted(x["cpa"] for x in v)
        cps = sorted(x["cps"] for x in v if x["cps"])
        print("%-6s %8d %12s %12s %14s" % (
            y, len(v),
            format(cpas[len(cpas) // 2], ",.0f").replace(",", " "),
            format(sum(cpas) / len(cpas), ",.0f").replace(",", " "),
            format(cps[len(cps) // 2], ",.0f").replace(",", " ") if cps else "—"))
    print("\nпо ивентам:")
    for y in sorted(by_year):
        for x in sorted(by_year[y], key=lambda z: z["cpa"]):
            print("  %s  %-44s CPA %7s ₽   ₽/S+ %9s" % (
                y, x["event"][:43],
                format(x["cpa"], ",.0f").replace(",", " "),
                format(x["cps"], ",.0f").replace(",", " ") if x["cps"] else "—"))


def cmd_budget(gc, cfg, target_sp, like):
    """Диапазон бюджета под цель по S+. Никогда не одно число: разброс цены
    целевого S+ внутри одного флайта бывает стократным."""
    _, rows = sheets._svodnaya_rows(gc, cfg)
    pts = []
    for r in rows:
        cost = common.num(r.get("Стоимость"))
        sp = common.num(r.get("S+ c рекламы"))
        if cost and sp:
            pts.append((cost / sp, r["event"], r["date"]))
    if not pts:
        print("Недостаточно данных.")
        return
    pts.sort()
    lo, mid, hi = pts[0], pts[len(pts) // 2], pts[-1]
    print("ОЦЕНКА БЮДЖЕТА ПОД %d S+ С РЕКЛАМЫ\n" % target_sp)
    print("  оптимистично (как «%s»):  %s ₽   (%s ₽ за S+)"
          % (lo[1][:34], format(lo[0] * target_sp, ",.0f").replace(",", " "),
             format(lo[0], ",.0f").replace(",", " ")))
    print("  реалистично (медиана):     %s ₽   (%s ₽ за S+)"
          % (format(mid[0] * target_sp, ",.0f").replace(",", " "),
             format(mid[0], ",.0f").replace(",", " ")))
    print("  пессимистично (как «%s»): %s ₽   (%s ₽ за S+)"
          % (hi[1][:34], format(hi[0] * target_sp, ",.0f").replace(",", " "),
             format(hi[0], ",.0f").replace(",", " ")))
    print("\n  Оценка по %d ивентам. Зависит от темы, сезона, доли новых каналов" % len(pts))
    print("  и от того, будет ли упор на нишевое ядро или на широкие каналы.")
    if like:
        m = [p for p in pts if like.lower() in p[1].lower()]
        if m:
            print("\n  По образцу «%s»: %s ₽" % (
                m[0][1], format(m[0][0] * target_sp, ",.0f").replace(",", " ")))


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("cmd", nargs="?")
    p.add_argument("arg", nargs="?")
    p.add_argument("--goal", default="quality", choices=list(GOALS))
    p.add_argument("--target-sp", type=int)
    p.add_argument("--like")
    a = p.parse_args()
    if not a.cmd:
        print(__doc__)
        return 1
    cfg = common.config()
    gc = common.gspread_client()
    if a.cmd == "channels":
        cmd_channels(gc, cfg, a.arg, a.goal)
    elif a.cmd == "history":
        cmd_history(gc, cfg, a.arg)
    elif a.cmd == "benchmarks":
        cmd_benchmarks(gc, cfg)
    elif a.cmd == "budget":
        cmd_budget(gc, cfg, a.target_sp or 50, a.like)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
