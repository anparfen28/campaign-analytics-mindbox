#!/usr/bin/env python3
"""Настройка скилла на нового пользователя. Запускается один раз при установке.

Скилл читает Trello и две Google-таблицы. Доступы должны быть ТВОИ — не того,
кто скилл собирал: у каждого свои права, и чужой токен рано или поздно протухнет
или отзовётся.

    python3 setup.py                 — проверить, чего не хватает, и подсказать
    python3 setup.py --trello        — записать ключ и токен Trello
    python3 setup.py --google <файл> — авторизовать Google по client secrets
"""
import argparse
import json
import os
import sys

import common

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

ENV_PATH = os.path.join(common.SKILL_DIR, ".env")
TOKEN_PATH = os.path.join(common.SKILL_DIR, "google_token.json")


def save_config(**kw):
    cfg = {}
    if os.path.exists(common.CONFIG_PATH):
        with open(common.CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    cfg.update({k: v for k, v in kw.items() if v})
    with open(common.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def setup_trello():
    print("\nTRELLO")
    print("  1. Открой https://trello.com/power-ups/admin — создай Power-Up, возьми API key")
    print("  2. На той же странице выпусти Token (нажми «Token» рядом с ключом)")
    print("  Доступ нужен только на чтение доски «Marketing | Campaigns».\n")
    key = input("  API key: ").strip()
    token = input("  Token:   ").strip()
    if not key or not token:
        print("  Пусто — ничего не записала.")
        return False
    # секреты в .env, а не в config.json: config попадает в бэкапы и репозитории
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("TRELLO_API_KEY=%s\nTRELLO_TOKEN=%s\n" % (key, token))
    os.chmod(ENV_PATH, 0o600)
    save_config(trello_env_path=ENV_PATH)
    print("  Записано в %s (права 600)" % ENV_PATH)
    return True


def setup_google(client_secrets):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("  Нет библиотеки. Установи:  pip3 install google-auth-oauthlib")
        return False
    if not os.path.exists(client_secrets):
        print("  Файл не найден: %s" % client_secrets)
        return False
    print("\n  Откроется браузер — войди тем аккаунтом, у которого есть доступ")
    print("  к таблицам «Посевы/Медиапланы 2026» и «Реклама // Анализ // Ивенты 2026».")
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)
    save_config(sheets_token_path=TOKEN_PATH, docs_token_path=TOKEN_PATH)
    print("  Токен записан в %s" % TOKEN_PATH)
    return True


def status():
    cfg = common.config()
    ok_trello = bool(cfg.get("trello_key") and cfg.get("trello_token"))
    tok = cfg.get("sheets_token_path")
    ok_google = bool(tok and os.path.exists(tok))

    print("СОСТОЯНИЕ НАСТРОЙКИ\n")
    print("  %s Trello" % ("OK " if ok_trello else "нет"))
    print("  %s Google Sheets / Docs" % ("OK " if ok_google else "нет"))
    if ok_google:
        try:
            scopes = json.load(open(tok)).get("scopes", [])
            missing = [s for s in SCOPES if s not in scopes]
            if missing:
                print("     ⚠ у токена нет прав: %s"
                      % ", ".join(s.rsplit("/", 1)[-1] for s in missing))
                print("       доки по ссылкам из карточек читаться не будут")
        except Exception:  # noqa: BLE001
            pass

    if not ok_trello:
        print("\n  Настроить Trello:  python3 setup.py --trello")
    if not ok_google:
        print("  Настроить Google:  python3 setup.py --google client_secret.json")
        print("    client_secret.json берётся в Google Cloud Console →")
        print("    APIs & Services → Credentials → Create OAuth client ID → Desktop app")
    if ok_trello and ok_google:
        print("\n  Всё на месте. Проверь связь:  python3 preflight.py")
    return 0 if (ok_trello and ok_google) else 1


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--trello", action="store_true")
    p.add_argument("--google")
    a = p.parse_args()
    if a.trello:
        setup_trello()
        return status()
    if a.google:
        setup_google(a.google)
        return status()
    return status()


if __name__ == "__main__":
    sys.exit(main())
