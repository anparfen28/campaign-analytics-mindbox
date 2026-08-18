#!/usr/bin/env python3
"""Проверка доступов. Запускать ПЕРВЫМ, до любого анализа.

Ответ, собранный на двух источниках из трёх, выглядит так же уверенно, как полный,
и потому опаснее отсутствия ответа. Поэтому: не хватает источника — останавливаемся
и говорим, чего именно не хватает.
"""
import sys

import common


def check_trello(cfg):
    if not cfg.get("trello_key") or not cfg.get("trello_token"):
        return False, "нет ключа/токена (config.json → trello_key, trello_token, или переменные TRELLO_API_KEY / TRELLO_TOKEN)"
    try:
        me = common.trello_get("/members/me", fields="username")
        board = common.trello_get(
            "/boards/%s" % cfg["trello_board_id"], fields="name,dateLastActivity"
        )
        lists = common.trello_get("/boards/%s/lists" % cfg["trello_board_id"], fields="name")
        done = [l["name"] for l in lists if l["name"].startswith("Готово")]
        if not done:
            return False, "на доске нет списков «Готово» — проверь, та ли доска"
        return True, "%s · доска «%s» · списки: %s · активность %s" % (
            me.get("username"), board.get("name"), ", ".join(done),
            (board.get("dateLastActivity") or "")[:10],
        )
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:160])


def check_sheet(gc, sheet_id, expect_tab=None):
    try:
        sh = gc.open_by_key(sheet_id)
        titles = [w.title.strip() for w in sh.worksheets()]
        if expect_tab and not any(expect_tab in t for t in titles):
            return False, "открылась «%s», но вкладки «%s» нет" % (sh.title, expect_tab)
        return True, "«%s» · вкладок %d" % (sh.title, len(titles))
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:160])


def main():
    cfg = common.config()
    results = []

    ok, msg = check_trello(cfg)
    results.append(("Trello «Marketing | Campaigns»", ok, msg))

    try:
        gc = common.gspread_client()
    except Exception as e:  # noqa: BLE001
        results.append(("Google Sheets", False, str(e)[:200]))
        gc = None

    if gc is not None:
        results.append(("Посевы/Медиапланы", *check_sheet(gc, cfg["sheet_posevy"], "Все каналы")))
        results.append(("Сводная по ивентам", *check_sheet(gc, cfg["sheet_svodnaya"], "Сводная")))

    print("ПРОВЕРКА ДОСТУПОВ")
    print("=" * 72)
    for name, ok, msg in results:
        print("  %s  %-30s %s" % ("OK  " if ok else "НЕТ ", name, msg))

    bad = [n for n, ok, _ in results if not ok]
    print("=" * 72)
    if bad:
        print("НЕ ХВАТАЕТ: %s" % ", ".join(bad))
        print("Работать на неполном наборе источников нельзя — ответ будет выглядеть")
        print("полным, но не будет им. Сообщи пользователю, чего не хватает.")
        return 1
    print("Все три источника доступны. Режим: ТОЛЬКО ЧТЕНИЕ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
