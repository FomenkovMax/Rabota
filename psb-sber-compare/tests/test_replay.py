"""Разбор по снимку страниц — без заходов на сайты."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import replay


def test_replay_parses_saved_page(tmp_path):
    bank = tmp_path / "sber"
    bank.mkdir()
    (bank / "001-credit.txt").write_text(
        "URL: https://www.sberbank.ru/ru/person/credits/money/consumer_unsecured\n"
        "H1: Кредит наличными\nTITLE: Кредит\nРАЗДЕЛ: Кредиты\nВКЛАДОК НАЖАТО: 1\n"
        "ССЫЛКИ ДЛЯ ОБХОДА (0):\n\nТЕКСТ:\nМеню\nКредит наличными\nСтавка\nот 20,4%\n",
        encoding="utf-8")
    lines = replay.report(tmp_path)
    assert lines and lines[0].startswith("Сбер\tКредиты\tКредит наличными\t20.4\tбазовая")
