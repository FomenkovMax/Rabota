"""Разбор страниц пакетов iqga.me/base/<id>/ (вопросы ЧГК с ответами и комментариями).

Без сторонних зависимостей. Используется для личной тренировки команды; в репозиторий попадают только
ID выбранных вопросов, а не их тексты (авторские права принадлежат авторам вопросов)."""
import html
import re
import time
import urllib.request

BASE = "https://iqga.me"
UA = "chgk-training-bot/0.1 (personal team training; github.com/FomenkovMax/Rabota)"


def fetch(path: str, delay: float = 1.5) -> str:
    """Скачивает страницу с паузой между запросами (вежливо к сайту)."""
    time.sleep(delay)
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"</p>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html.unescape(fragment)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", fragment)).strip()


def _field(block: str, name: str) -> str:
    m = re.search(rf"<b>{name}:</b>(.*?)(?=<p><b>|</div>|$)", block, flags=re.S)
    return _text(m.group(1)) if m else ""


def split_answer(raw: str) -> tuple[str, list[str], list[str]]:
    """«монетка\n Зачет: монета» -> ("монетка", ["монета"], []). Незачёт отдельно."""
    answer, accepted, rejected = [], [], []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"(Зач[её]т|Незач[её]т)\s*:\s*(.*)", line, flags=re.I)
        if not m:
            answer.append(line)
        else:
            items = [x.strip() for x in re.split(r"[;,]", m.group(2)) if x.strip()]
            (rejected if m.group(1).lower().startswith("не") else accepted).extend(items)
    return " ".join(a for a in answer if a), accepted, rejected


def parse_pack(page: str, pack_id: int) -> list[dict]:
    """Список вопросов пакета: id, номер, текст, ответ, зачёт, комментарий, источник, автор, ссылка."""
    title_m = re.search(r"<title>(.*?)</title>", page, flags=re.S)
    pack_title = _text(title_m.group(1)).split(" - ")[0] if title_m else str(pack_id)
    out = []
    for li in re.split(r'<li id="question-', page)[1:]:
        qid = int(re.match(r"(\d+)", li).group(1))
        num_m = re.search(r'data-question="(\d+)"', li)
        # текст вопроса: между блоком рейтинга и ссылкой «Ответ»
        body = li.split('<div class="comments', 1)[0]
        pre, _, ans_block = body.partition('<span class="js answer-link"')
        pre = re.split(r'</div></div>\s*', pre)[-1]
        ans_block = ans_block.split('<div class="answer hidden', 1)[-1]
        q = {
            "iqga_id": qid,
            "pack": pack_id,
            "pack_title": pack_title,
            "number": int(num_m.group(1)) if num_m else None,
            "text": _text(pre),
            "answer": _field(ans_block, "Ответ"),
            "accepted_raw": _field(ans_block, "Зачёт"),
            "rejected_raw": _field(ans_block, "Незачёт"),
            "comment": _field(ans_block, "Комментарий"),
            "source": _field(ans_block, "Источник"),
            "author": _field(ans_block, "Автор"),
            "url": f"{BASE}/base/{pack_id}/{qid}/",
            "has_media": bool(re.search(r"<img|<audio|<video|Раздаточн", pre, flags=re.I)),
        }
        q["answer"], acc, rej = split_answer(q["answer"])
        q["accepted"] = acc + [x.strip() for x in re.split(r"[;,]", q.pop("accepted_raw")) if x.strip()]
        q["rejected"] = rej + [x.strip() for x in re.split(r"[;,]", q.pop("rejected_raw")) if x.strip()]
        if q["text"] and q["answer"]:
            out.append(q)
    return out
