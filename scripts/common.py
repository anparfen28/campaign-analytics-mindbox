"""Общая инфраструктура: конфиг, доступы, парсеры грязных данных.

ВАЖНО: во всём скилле нет ни одной функции записи в Trello или Google Sheets.
Источники принадлежат живой команде — мы их только читаем.
"""
import json
import os
import re
import urllib.parse
import urllib.request

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE = os.path.join(SKILL_DIR, "knowledge")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")

DEFAULTS = {
    "trello_board_id": "676ab209bac2068716b578d9",
    "sheet_posevy": "1C_BgPUrGDmLUdEs39MSoTE7vYTgCjUOMoYpEqfWXXpQ",
    "sheet_svodnaya": "1cLlJufQpbsAJTKgN-GhljRGflv_zvL86W9t_124OMcQ",
    "gid_svodnaya": 1505179501,
    "gid_all_channels": 439551760,
    "gid_template": 1273501063,
}


def _read_env_file(path):
    """KEY=VALUE из .env. Секреты держим в таких файлах, а не в config.json:
    config.json может попасть в бэкап/репозиторий, а .env повсеместно исключён."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def config():
    """Конфиг поверх дефолтов. Секреты подтягиваются из .env или окружения."""
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))

    env = _read_env_file(cfg.get("trello_env_path"))
    for env_key, cfg_key in (("TRELLO_API_KEY", "trello_key"),
                             ("TRELLO_TOKEN", "trello_token")):
        # приоритет: переменная окружения → .env → то, что уже в конфиге
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
        elif env.get(env_key) and not cfg.get(cfg_key):
            cfg[cfg_key] = env[env_key]
    return cfg


# ─────────────────────────── Trello (только GET) ───────────────────────────

def trello_get(path, **params):
    cfg = config()
    params.update(key=cfg.get("trello_key", ""), token=cfg.get("trello_token", ""))
    url = "https://api.trello.com/1" + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


# ─────────────────────────── Google Sheets (только чтение) ───────────────────

def gspread_client():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    import gspread

    cfg = config()
    tok = cfg.get("sheets_token_path")
    if not tok or not os.path.exists(tok):
        raise RuntimeError(
            "Нет токена Google Sheets. Укажи sheets_token_path в config.json — "
            "путь к OAuth-токену со scope spreadsheets(.readonly)."
        )
    scopes = json.load(open(tok)).get(
        "scopes", ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    creds = Credentials.from_authorized_user_file(tok, scopes)
    if not creds.valid:
        creds.refresh(Request())
        with open(tok, "w") as f:
            f.write(creds.to_json())
    return gspread.authorize(creds)


# ─────────────────────────── Парсеры грязных данных ─────────────────────────

_NBSP = " "
_ZWNJ = "‌"

# Гомоглифы: в заголовках встречаются СРА / СR / СTR с русской «С»
_HOMOGLYPHS = str.maketrans({"С": "C", "Р": "P", "А": "A", "Т": "T", "О": "O", "Е": "E"})


def norm_header(s):
    """Нормализованное имя колонки: колонки матчим по имени, НИКОГДА по позиции."""
    s = str(s).replace(_NBSP, " ").replace(_ZWNJ, "").replace("\r", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def header_key(s):
    """Ключ для сравнения заголовков: без регистра, без гомоглифов, без пунктуации."""
    s = norm_header(s).translate(_HOMOGLYPHS).lower()
    return re.sub(r"[^a-zа-я0-9]+", "", s)


# Синонимы заголовков между вкладками разных поколений
SYNONYMS = {
    "регистрациифакт": ["заявкифакт", "отправкаформфакт", "заявкауспешнаяотправкаформы"],
    "охватпубликации": ["охват"],
    "датапубликации": ["дата"],
    "гипотезы": ["гипотеза"],
}


def find_col(headers, *names):
    """Индекс колонки по любому из имён с учётом синонимов. None если нет."""
    keys = [header_key(h) for h in headers]
    for name in names:
        k = header_key(name)
        cands = [k] + SYNONYMS.get(k, [])
        for c in cands:
            if c in keys:
                return keys.index(c)
    return None


def num(value):
    """Число из грязной ячейки или из прозы.

    Умеет: 'р.130 000', 'р.50 000,00', '2 723р.', '1 410 634', '2 700 руб.', '1,56%'.
    Возвращает None для пустых, '-' и ошибок формул (#DIV/0! и т.п.) — это НЕ ноль,
    это отсутствие данных, и путать их нельзя.
    """
    if value is None:
        return None
    s = str(value).replace(_NBSP, " ").replace(_ZWNJ, "").strip()
    if not s or s in {"-", "—", "–"} or s.startswith("#"):
        return None
    # склеиваем разделитель тысяч: '130 000' -> '130000'
    s = re.sub(r"(?<=\d)[ ](?=\d{3}\b)", "", s)
    m = re.findall(r"\d+(?:[.,]\d+)?", s)
    if not m:
        return None
    try:
        return float(max(m, key=len).replace(",", "."))
    except ValueError:
        return None


def numbers_in_prose(text):
    """Все числа из текста комментария — для числового отпечатка при сшивке."""
    s = str(text).replace(_NBSP, " ").replace(_ZWNJ, "")
    s = re.sub(r"(?<=\d)[ ](?=\d{3}\b)", "", s)
    out = set()
    for tok in re.findall(r"\d+(?:[.,]\d+)?", s):
        try:
            out.add(float(tok.replace(",", ".")))
        except ValueError:
            pass
    return out


_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}


def dates_in_name(name):
    """Даты (день, месяц), зашитые в название карточки Trello.

    '12.02' -> (12,2) · '21 мая' -> (21,5) · '22 июля' -> (22,7)
    """
    out = set()
    for dd, mm in re.findall(r"\b(\d{1,2})[.\s](\d{2})\b", name):
        d, m = int(dd), int(mm)
        if 1 <= d <= 31 and 1 <= m <= 12:
            out.add((d, m))
    for dd, word in re.findall(r"\b(\d{1,2})\s+([а-яё]+)", name.lower()):
        for stem, m in _MONTHS.items():
            if word.startswith(stem[:4]):
                out.add((int(dd), m))
                break
    return out


def months_in_name(name):
    """Месяцы без дня — запасной вариант ('ивент c исследованием (апрель)')."""
    out = set()
    for word in re.findall(r"[а-яё]+", name.lower()):
        for stem, m in _MONTHS.items():
            if len(stem) >= 4 and word.startswith(stem[:4]):
                out.add(m)
    return out


def tme(value):
    """Нормализованный юзернейм Telegram-канала из ссылки."""
    m = re.search(r"t\.me/([A-Za-z0-9_]+)", str(value))
    return m.group(1).lower() if m else None


# ─────────────────────────── Очистка комментариев ───────────────────────────

def clean_comment(text):
    """Очистка по порядку из references/04_feedback.md.

    Возвращает dict: body (очищенный текст), quotes (чужие цитаты — отдельно!),
    links (по ним НАДО сходить), has_card (признак @card), had_image.
    """
    raw = str(text)
    had_image = bool(re.search(r"!\[[^\]]*\]\(", raw))
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw)          # картинки

    links = []
    def _link(m):
        links.append(m.group(2).strip().strip('"\''))
        return m.group(1)
    s = re.sub(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)", _link, s)  # ссылки -> anchor text
    links += re.findall(r"https?://[^\s)\"'\]]+", s)
    s = re.sub(r"https?://[^\s)\"'\]]+", " ", s)

    # цитаты изолируем, а не удаляем: это ЧУЖИЕ слова, часто чтобы возразить
    quotes, body = [], []
    for line in s.split("\n"):
        (quotes if line.lstrip().startswith(">") else body).append(line.lstrip("> "))
    s = "\n".join(body)

    has_card = "@card" in s
    s = re.sub(r"@card\b", " КАРТОЧКА ", s)                # сохраняем признак
    s = re.sub(r"@[\w.\-]+", " ", s)                        # прочие @-меншены
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!])", r"\1", s)      # экранирование Trello
    s = s.replace(_ZWNJ, "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()

    return {
        "body": s,
        "quotes": "\n".join(q for q in quotes if q.strip()).strip(),
        "links": sorted({l for l in links if l.startswith("http")}),
        "has_card": has_card,
        "had_image": had_image,
        "empty_after_clean": len(re.sub(r"\W+", "", s)) == 0,
    }


def ensure_knowledge():
    os.makedirs(KNOWLEDGE, exist_ok=True)
    return KNOWLEDGE
