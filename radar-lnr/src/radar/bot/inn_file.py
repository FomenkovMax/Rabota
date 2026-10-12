"""Разбор файла со списком ИНН (.xlsx / .csv / .txt), до 50 штук."""
from __future__ import annotations

import io
import re

from ..llm.verify import inn_checksum_ok

MAX_INNS = 50
SUPPORTED = (".xlsx", ".csv", ".txt")
_INN_RE = re.compile(r"(?<!\d)(\d{10}|\d{12})(?!\d)")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _xlsx_texts(raw: bytes) -> list[str]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    out = []
    for ws in wb:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if v is None:
                    continue
                if isinstance(v, (int, float)) and float(v).is_integer():
                    s = str(int(v))
                    # Excel теряет ведущий ноль у числовых ИНН: 9 цифр -> 10, 11 -> 12
                    s = s.zfill(10) if len(s) == 9 else s.zfill(12) if len(s) == 11 else s
                    out.append(s)
                else:
                    out.append(str(v))
    return out


def parse_inn_file(filename: str, raw: bytes) -> tuple[list[str], list[str], bool]:
    """-> (валидные ИНН без дублей, не прошедшие проверку, было ли обрезано до MAX_INNS)."""
    name = filename.lower()
    if not name.endswith(SUPPORTED):
        raise ValueError("Поддерживаются файлы .xlsx, .csv, .txt")
    texts = _xlsx_texts(raw) if name.endswith(".xlsx") else [_decode(raw)]
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for t in texts:
        for inn in _INN_RE.findall(t):
            if inn in seen:
                continue
            seen.add(inn)
            (valid if inn_checksum_ok(inn) else invalid).append(inn)
    return valid[:MAX_INNS], invalid, len(valid) > MAX_INNS
