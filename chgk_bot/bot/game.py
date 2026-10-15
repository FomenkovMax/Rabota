"""Командная игра по правилам спортивного ЧГК: туры по N вопросов, 60 секунд, отвечает капитан.

Здесь только состояние и подсчёты (без Telegram), чтобы это можно было тестировать."""
import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class TeamGame:
    chat_id: int
    captain_id: int
    captain_name: str
    queue: list[dict]
    per_tour: int = 12
    idx: int = 0                                   # номер текущего вопроса (с нуля)
    results: list = field(default_factory=list)    # True / False / None для каждого вопроса
    phase: str = "lobby"                           # lobby | think | answer | judging | between | finished
    task: asyncio.Task | None = None
    timer_msg_id: int | None = None
    timer_is_anim: bool = False
    answer_msg_id: int | None = None
    started: float = field(default_factory=time.time)

    def __post_init__(self):
        self.results = [None] * len(self.queue)

    @property
    def total(self) -> int:
        return len(self.queue)

    @property
    def tours(self) -> int:
        return -(-self.total // self.per_tour)   # округление вверх

    @property
    def tour(self) -> int:
        return self.idx // self.per_tour + 1

    @property
    def number_in_tour(self) -> int:
        return self.idx % self.per_tour + 1

    @property
    def current(self) -> dict:
        return self.queue[self.idx]

    def score(self) -> int:
        return sum(1 for r in self.results if r)

    def tour_slice(self, tour: int) -> list:
        return self.results[(tour - 1) * self.per_tour: tour * self.per_tour]

    def tour_score(self, tour: int) -> tuple[int, int]:
        """(взято, всего вопросов в туре)."""
        part = self.tour_slice(tour)
        return sum(1 for r in part if r), len(part)

    def is_last_in_tour(self) -> bool:
        return (self.idx + 1) % self.per_tour == 0 or self.is_last()

    def is_last(self) -> bool:
        return self.idx + 1 >= self.total

    def answered(self) -> int:
        return sum(1 for r in self.results if r is not None)


def tour_line(game: TeamGame, tour: int) -> str:
    got, n = game.tour_score(tour)
    marks = "".join("🟩" if r else "🟥" if r is False else "⬜" for r in game.tour_slice(tour))
    return f"Тур {tour}: <b>{got} из {n}</b>  {marks}"


def final_summary(game: TeamGame, stopped: bool = False) -> str:
    played = game.answered()
    head = "🛑 <b>Игра остановлена</b>" if stopped else "🏁 <b>Игра окончена!</b>"
    lines = [head, ""] + [tour_line(game, t) for t in range(1, game.tours + 1) if game.tour_slice(t) and any(
        r is not None for r in game.tour_slice(t))]
    pct = round(100 * game.score() / played) if played else 0
    lines += ["", f"Итого: <b>{game.score()} из {played}</b> сыгранных ({pct}%)"]
    return "\n".join(lines)
