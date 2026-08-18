#!/usr/bin/env python3
"""HTML-таблица каналов с цветовой разметкой.

Смысл не в красоте, а в том, чтобы плохое было видно за три секунды, без чтения:
красное — снимать, жёлтое — под вопросом, зелёное — ядро, которое работает.

    python3 report.py channels <gid> [--out файл.html] [--open]
"""
import argparse
import html
import os
import subprocess
import sys

import common
import metrics
import sheets

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#6b7280;--line:#e5e7eb;
--good:#e8f5ec;--goodl:#39AA5D;--warn:#fff8e1;--warnl:#d9a300;--bad:#fdeaea;--badl:#d64545}
*{box-sizing:border-box}
body{margin:0;padding:28px;font-family:-apple-system,'Golos Text',Segoe UI,sans-serif;
background:var(--bg);color:var(--fg);font-size:14px;line-height:1.45}
h1{font-size:19px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:18px}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
.card{border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:130px}
.card .n{font-size:19px;font-weight:600}
.card .l{color:var(--mut);font-size:12px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th{text-align:right;font-weight:600;font-size:12px;color:var(--mut);
padding:8px 10px;border-bottom:2px solid var(--line);white-space:nowrap}
th:first-child{text-align:left}
td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
td:first-child{text-align:left;font-weight:500}
tr.good{background:var(--good)} tr.warn{background:var(--warn)} tr.bad{background:var(--bad)}
tr.good td:first-child{box-shadow:inset 3px 0 var(--goodl)}
tr.warn td:first-child{box-shadow:inset 3px 0 var(--warnl)}
tr.bad td:first-child{box-shadow:inset 3px 0 var(--badl)}
.tag{font-size:11px;color:var(--mut)}
.legend{margin-top:14px;font-size:12px;color:var(--mut)}
.legend span{display:inline-block;margin-right:14px}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#9ca3af;--line:#2a2a2a;
--good:#12301c;--warn:#332a0d;--bad:#3a1717}}
"""


def classify(row, median_cps):
    """Красное — деньги потрачены впустую. Зелёное — дёшево и качественно."""
    cps = row.get("cost_per_target_sp")
    fact = row.get("fact") or 0
    if fact == 0 or cps is None:
        return "bad", "нет целевых S+"
    if cps <= median_cps * 0.5:
        return "good", ""
    if cps >= median_cps * 2:
        return "bad", "дорого за целевого"
    if row.get("is_new") and cps > median_cps:
        return "warn", "новый и дороже медианы"
    if cps > median_cps:
        return "warn", ""
    return "good", ""


def build(title, rows, totals):
    rows = metrics.enrich(rows)
    cps_vals = sorted(r["cost_per_target_sp"] for r in rows if r["cost_per_target_sp"])
    median = cps_vals[len(cps_vals) // 2] if cps_vals else 1
    fmt = lambda v, d=0: format(v, ",.%df" % d).replace(",", " ") if v else "—"

    cards = "".join(
        '<div class="card"><div class="n">%s</div><div class="l">%s</div></div>' % (v, l)
        for v, l in [
            (fmt(totals["cost"]) + " ₽", "бюджет"),
            (fmt(totals["fact"]), "регистраций"),
            (fmt(totals["target_sp"]), "целевых S+"),
            (fmt(totals["cost"] / totals["target_sp"]) + " ₽" if totals["target_sp"] else "—",
             "за целевого S+"),
        ])

    body = []
    for r in sorted(rows, key=lambda x: (x["cost_per_target_sp"] is None,
                                         x["cost_per_target_sp"] or 0)):
        cls, note = classify(r, median)
        body.append(
            "<tr class='%s'><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                cls, html.escape(r["channel"][:34]),
                (" <span class='tag'>· %s</span>" % note) if note else "",
                fmt(r["cost"]),
                fmt(r["fact"]),
                (fmt(r["plan_pct"]) + "%") if r["plan_pct"] else "—",
                fmt(r["cpa"]),
                fmt(r["target_sp"]),
                fmt(r["cost_per_target_sp"]),
                "да" if r["is_new"] else ""))

    return """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>%s</style></head><body>
<h1>%s</h1><div class="sub">каналов %d · ранжирование по цене целевого S+</div>
<div class="cards">%s</div>
<table><thead><tr><th>канал</th><th>бюджет</th><th>рег</th><th>%% плана</th>
<th>CPA</th><th>цел. S+</th><th>₽ / целевой</th><th>новый</th></tr></thead>
<tbody>%s</tbody></table>
<div class="legend">
<span><i class="dot" style="background:#39AA5D"></i>работает — оставляем</span>
<span><i class="dot" style="background:#d9a300"></i>под вопросом</span>
<span><i class="dot" style="background:#d64545"></i>снимать или пересматривать</span>
</div></body></html>""" % (html.escape(title), CSS, html.escape(title),
                           len(rows), cards, "".join(body))


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("cmd", nargs="?")
    p.add_argument("gid", nargs="?")
    p.add_argument("--out")
    p.add_argument("--open", action="store_true")
    a = p.parse_args()
    if a.cmd != "channels" or not a.gid:
        print(__doc__)
        return 1

    cfg = common.config()
    gc = common.gspread_client()
    title, rows = sheets.read_tab(gc, cfg, a.gid)
    totals = {"cost": sum(r["cost"] or 0 for r in rows),
              "fact": sum(r["fact"] or 0 for r in rows),
              "target_sp": sum(r["target_sp"] or 0 for r in rows)}
    out = a.out or os.path.join(common.ensure_knowledge(),
                                "report_%s.html" % a.gid)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(title, rows, totals))
    print(out)
    if a.open:
        subprocess.run(["open", out], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
