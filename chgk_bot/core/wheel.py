"""Волчок «Что? Где? Когда?»: сервер выбирает сектор, клиент только красиво крутит стрелку."""
import random

N_SECTORS = 13


def pick_sector(played: set[int] | list[int], n: int = N_SECTORS, rng: random.Random | None = None) -> int | None:
    """Случайный сектор; если он уже сыгран — идём по часовой до первого свободного. None — все сыграны."""
    played = set(played)
    if len(played) >= n:
        return None
    r = rng or random
    target = r.randrange(n)
    for step in range(n):
        s = (target + step) % n
        if s not in played:
            return s
    return None


def spin(played, n: int = N_SECTORS, rng: random.Random | None = None) -> dict | None:
    """Параметры анимации: сектор, число оборотов, длительность и смещение внутри сектора (доля ширины, ±0.35)."""
    sector = pick_sector(played, n, rng)
    if sector is None:
        return None
    r = rng or random
    return {"sector": sector, "turns": r.randint(4, 6), "duration_ms": r.randint(4200, 5600),
            "offset": round(r.uniform(-0.35, 0.35), 3), "n": n}
