#!/usr/bin/env python3
"""Чтение Google Docs по ссылкам из карточек Trello.

В комментариях лежат ссылки на доки, и часто основной анализ именно там, а в карточке
только выжимка в три строки. Разбор текстов Маши Скударновой по Фоксфорду — отдельный
документ. Кто не открыл его, не знает половины выводов.

    python3 docs.py <url|id>
    python3 docs.py --from-card <дата|id>     # все доки, упомянутые в карточке
"""
import re
import sys

import common

SCOPES = ["https://www.googleapis.com/auth/documents.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    import os

    cfg = common.config()
    path = cfg.get("docs_token_path")
    if not path or not os.path.exists(path):
        raise RuntimeError(
            "Нет токена Google Docs. Укажи docs_token_path в config.json — "
            "нужен scope documents.readonly."
        )
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        with open(path, "w") as f:
            f.write(creds.to_json())
    return creds


def doc_id(url):
    m = re.search(r"/document/d/([A-Za-z0-9_\-]+)", str(url))
    if m:
        return m.group(1)
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_\-]+)", str(url))
    return None if m else str(url).strip()


def read_doc(url_or_id):
    """Плоский текст документа: заголовки, абзацы, таблицы."""
    from googleapiclient.discovery import build

    did = doc_id(url_or_id)
    svc = build("docs", "v1", credentials=_creds())
    doc = svc.documents().get(documentId=did).execute()

    def para_text(el):
        out = []
        for r in el.get("elements", []):
            t = r.get("textRun", {}).get("content")
            if t:
                out.append(t)
        return "".join(out)

    lines = []

    def walk(content):
        for el in content:
            if "paragraph" in el:
                style = el["paragraph"].get("paragraphStyle", {}).get("namedStyleType", "")
                text = para_text(el["paragraph"]).rstrip("\n")
                if not text.strip():
                    continue
                if style.startswith("HEADING"):
                    lines.append("\n" + "#" * min(int(style[-1]) + 1, 6) + " " + text)
                else:
                    lines.append(text)
            elif "table" in el:
                for row in el["table"].get("tableRows", []):
                    cells = []
                    for cell in row.get("tableCells", []):
                        buf = []
                        for c in cell.get("content", []):
                            if "paragraph" in c:
                                buf.append(para_text(c["paragraph"]).strip())
                        cells.append(" ".join(x for x in buf if x))
                    lines.append(" | ".join(cells))
            elif "tableOfContents" in el:
                continue

    walk(doc.get("body", {}).get("content", []))
    return doc.get("title", "(без названия)"), "\n".join(lines)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1

    if args[0] == "--from-card":
        import trello
        idx = trello.build_index()
        key = args[1]
        card = None
        if "." in key:
            p = key.split(".")
            hits, _ = trello.find_by_date(idx, int(p[0]), int(p[1]))
            card = hits[0] if len(hits) == 1 else None
        if card is None:
            card = next((c for c in idx if key in (c["id"], c["url"])
                         or key.lower() in c["name"].lower()), None)
        if card is None:
            print("Карточка не найдена")
            return 1
        links = set()
        for c in trello.get_comments(card["id"]):
            links |= {l for l in c["links"] if "/document/d/" in l}
        print("КАРТОЧКА: %s — документов: %d\n" % (card["name"], len(links)))
        for l in sorted(links):
            try:
                title, text = read_doc(l)
                print("=" * 76)
                print("ДОКУМЕНТ: %s\n%s\n" % (title, l))
                print(text[:12000])
            except Exception as e:  # noqa: BLE001
                print("не удалось прочитать %s — %s" % (l, str(e)[:120]))
        return 0

    title, text = read_doc(args[0])
    print("ДОКУМЕНТ: %s\n%s" % (title, "=" * 76))
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
