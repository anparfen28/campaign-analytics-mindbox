#!/usr/bin/env python3
"""Сборка базового знания: бенчмарки и досье площадок.

Зачем. Скилл, который умеет считать, но не знает, что такое «нормально», —
это аналитик без опыта. Он посчитает CPA 3 700 ₽ и не скажет, много это или мало,
пока не сделает пять запросов. Здесь один раз считается база: сколько стоит
регистрация и целевой лид в норме, какие площадки составляют ядро, какие выгорают.

Запускать при установке и раз в месяц-полтора. Результат — в knowledge/.

    python3 bootstrap.py [--out-md]
"""
import argparse
import collections
import json
import os
import re
import statistics
import sys

import common
import sheets


def median(values):
    v = [x for x in values if x]
    return statistics.median(v) if v else None


def build_benchmarks(gc, cfg):
    """Из строк ивентов, а не из ячеек со средними — в них подтверждённые ошибки."""
    _, rows = sheets._svodnaya_rows(gc, cfg)
    by_year = collections.defaultdict(list)
    for r in rows:
        year = re.split(r"[./]", r["date"])[-1]
        cost = common.num(r.get("Стоимость"))
        regs = common.num(r.get("Регистрации с платной"))
        sp = common.num(r.get("S+ c рекламы"))
        ctr = common.num(r.get("CTR"))
        cr = common.num(r.get("CR"))
        if not (cost and regs):
            continue
        by_year[year].append({
            "event": r["event"], "date": r["date"], "cost": cost, "regs": regs,
            "cpa": cost / regs, "sp": sp, "cost_per_sp": cost / sp if sp else None,
            "ctr": ctr, "cr": cr,
        })

    out = {"generated_from": "строки ивентов сводной", "years": {}}
    for year, items in sorted(by_year.items()):
        out["years"][year] = {
            "events": len(items),
            "cpa_median": round(median(x["cpa"] for x in items) or 0),
            "cpa_min": round(min(x["cpa"] for x in items)),
            "cpa_max": round(max(x["cpa"] for x in items)),
            "cost_per_sp_median": round(median(x["cost_per_sp"] for x in items) or 0),
            "budget_median": round(median(x["cost"] for x in items) or 0),
        }
    out["events"] = [
        {k: (round(v) if isinstance(v, float) else v) for k, v in x.items()}
        for items in by_year.values() for x in items
    ]
    return out


def build_channels(gc, cfg):
    """Досье площадки: история, тренд, вердикт.

    Целевых S+ во «Все каналы» нет — только S+. Поэтому вердикт строим на CPA
    и его динамике; цену целевого лида считаем по вкладкам, когда она нужна.
    """
    rows = sheets.read_all_channels(gc, cfg)
    # Группируем по ссылке t.me, а не по названию: одна площадка пишется
    # по-разному («CRM CJM FM» и «CRM⚡️CJM FM», «Фудтех» и «#Фудтех»),
    # и по названию история одного канала распадается на два огрызка.
    by_channel = collections.defaultdict(list)
    for r in rows:
        if not r["channel"]:
            continue
        key = r["tme"] or re.sub(r"[^а-яa-z0-9]", "", r["channel"].lower())
        by_channel[key].append(r)

    out = []
    for key, items in by_channel.items():
        # каноническое имя — самое частое написание
        name = collections.Counter(
            i["channel"].strip() for i in items if i["channel"]).most_common(1)[0][0]
        cpas = []
        by_year = collections.defaultdict(list)
        for i in items:
            cpa = i["cpa"] or (i["cost"] / i["regs"] if i["cost"] and i["regs"] else None)
            if cpa:
                cpas.append(cpa)
                by_year[i["year"]].append(cpa)
        spend = sum(i["cost"] or 0 for i in items)
        regs = sum(i["regs"] or 0 for i in items)
        sp = sum(i["sp"] or 0 for i in items)

        trend = None
        years = sorted(by_year)
        if len(years) >= 2:
            first, last = median(by_year[years[0]]), median(by_year[years[-1]])
            if first and last:
                trend = round(last / first, 2)

        rec = {
            "channel": name,
            "tme": next((i["tme"] for i in items if i["tme"]), None),
            "placements": len(items),
            "years": years,
            "spend_total": round(spend),
            "regs_total": round(regs),
            "sp_total": round(sp),
            "cpa_median": round(median(cpas)) if cpas else None,
            "cpa_by_year": {y: round(median(v)) for y, v in by_year.items() if median(v)},
            "cost_per_sp": round(spend / sp) if sp else None,
            "trend_ratio": trend,
            "flights": sorted({i["flight"] for i in items if i["flight"]}),
        }
        out.append(rec)
    out.sort(key=lambda x: -x["placements"])
    return out


def verdicts(channels, bench):
    """Ядро, выгорающие и разовые провалы — то, что аналитик держит в голове."""
    ref = bench["years"].get("2026", {}).get("cpa_median") or 3000
    core, burning, failed = [], [], []
    for c in channels:
        if c["placements"] >= 4 and c["cpa_median"] and c["cpa_median"] <= ref * 0.5:
            core.append(c)
        if c["trend_ratio"] and c["trend_ratio"] >= 2 and c["placements"] >= 4:
            burning.append(c)
        if c["placements"] == 1 and c["spend_total"] >= 50000 and (c["regs_total"] or 0) <= 12:
            failed.append(c)
    core.sort(key=lambda x: x["cpa_median"])
    burning.sort(key=lambda x: -x["trend_ratio"])
    failed.sort(key=lambda x: -x["spend_total"])
    return core[:12], burning[:8], failed[:8]


def to_markdown(bench, channels, core, burning, failed):
    fmt = lambda v: format(v, ",.0f").replace(",", " ") if v else "—"
    L = ["# Базовое знание о рекламе Mindbox",
         "",
         "Пересчитывается из источников скриптом `bootstrap.py`. Это ориентиры,",
         "с которыми сравнивается новая кампания, а не истина: данные в таблицах —",
         "ручная копия из BI, и они меняются.",
         "",
         "## Бенчмарки по годам", "",
         "| Год | Ивентов | CPA медиана | CPA разброс | Цена S+ медиана | Бюджет медиана |",
         "|---|---|---|---|---|---|"]
    for year, b in sorted(bench["years"].items()):
        L.append("| %s | %d | %s ₽ | %s–%s ₽ | %s ₽ | %s ₽ |" % (
            year, b["events"], fmt(b["cpa_median"]), fmt(b["cpa_min"]),
            fmt(b["cpa_max"]), fmt(b["cost_per_sp_median"]), fmt(b["budget_median"])))

    L += ["", "Читать так: CPA около медианы года — норма, вдвое выше — разбираться.",
          "Цена S+ — главный ориентир: именно за квалифицированный контакт платит бизнес.",
          "", "## Ядро: площадки, которые работают стабильно", "",
          "Берутся почти всегда, CPA вдвое ниже медианы года, история от четырёх размещений.", "",
          "| Площадка | Размещений | CPA медиана | Всего потрачено | S+ |",
          "|---|---|---|---|---|"]
    for c in core:
        L.append("| %s | %d | %s ₽ | %s ₽ | %s |" % (
            c["channel"], c["placements"], fmt(c["cpa_median"]),
            fmt(c["spend_total"]), fmt(c["sp_total"])))

    L += ["", "## Выгорающие: CPA вырос вдвое и больше", "",
          "| Площадка | Размещений | CPA по годам | Рост |", "|---|---|---|---|"]
    for c in burning:
        years = " → ".join("%s: %s" % (y, fmt(v)) for y, v in sorted(c["cpa_by_year"].items()))
        L.append("| %s | %d | %s | ×%.1f |" % (
            c["channel"], c["placements"], years, c["trend_ratio"]))

    L += ["", "Выгорание — не приговор, а повод пересобрать цену: платить прежние деньги",
          "за падающий охват значит финансировать чужую инерцию.", "",
          "## Разовые дорогие провалы", "",
          "Одно размещение, крупный чек, почти нет регистраций. Именно так выглядит",
          "риск нового канала, когда ему дают большой бюджет вслепую.", "",
          "| Площадка | Потрачено | Регистраций |", "|---|---|---|"]
    for c in failed:
        L.append("| %s | %s ₽ | %s |" % (c["channel"], fmt(c["spend_total"]), fmt(c["regs_total"])))

    L += ["", "## Что это значит при подборе каналов", "",
          "1. Ядро даёт дешёвые и качественные лиды, но у него ограниченный охват —",
          "   на объём одного ядра плана не набрать.",
          "2. Широкие каналы дают охват, но по цене целевого лида проигрывают в разы.",
          "3. Новый канал заводить минимальным чеком. Большой бюджет в непроверенную",
          "   площадку — самая дорогая ошибка в истории этих кампаний.",
          "4. Профильность по индустрии — гипотеза, а не гарантия: проверяй цифрами.", ""]
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out-md", action="store_true")
    a = p.parse_args()

    cfg = common.config()
    gc = common.gspread_client()
    kn = common.ensure_knowledge()

    print("считаю бенчмарки…")
    bench = build_benchmarks(gc, cfg)
    print("собираю досье площадок…")
    channels = build_channels(gc, cfg)
    core, burning, failed = verdicts(channels, bench)

    with open(os.path.join(kn, "benchmarks.json"), "w", encoding="utf-8") as f:
        json.dump(bench, f, ensure_ascii=False, indent=1)
    with open(os.path.join(kn, "channels.jsonl"), "w", encoding="utf-8") as f:
        for c in channels:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    md = to_markdown(bench, channels, core, burning, failed)
    path = os.path.join(common.SKILL_DIR, "references", "09_baseline.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    print("\nплощадок в досье: %d · ядро: %d · выгорающих: %d · провалов: %d"
          % (len(channels), len(core), len(burning), len(failed)))
    print("записано: knowledge/benchmarks.json, knowledge/channels.jsonl,")
    print("          references/09_baseline.md")
    if a.out_md:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
