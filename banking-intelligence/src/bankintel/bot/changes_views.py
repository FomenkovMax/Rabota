from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.cycle import MARK
from bankintel.formatting import fmt_msk
from bankintel.monitor import monitoring_status, recent_changes

LIMIT = 20


def parse_days(args: str | None) -> int:
    if not args or not args.strip():
        return 7
    try:
        days = int(args.strip())
    except ValueError:
        raise ValueError("Формат: /changes [число дней], например /changes 30") from None
    if not 1 <= days <= 90:
        raise ValueError("Допустимо от 1 до 90 дней")
    return days


def _dt(iso: str | None) -> str:
    return fmt_msk(iso)


async def changes_text(session: AsyncSession, days: int) -> str:
    st = await monitoring_status(session)
    now = datetime.now(UTC)
    items = await recent_changes(session, now - timedelta(days=days))
    head = f"🔔 <b>Изменения за {days} дн.</b>"
    watch = f"Наблюдение ведётся с {_dt(st['since'])}; сравнений с предыдущим запуском: {st['comparisons']}."
    if not st["has_data"]:
        return f"{head}\nСбор данных ещё не выполнялся — сравнивать не с чем."
    if not items:
        note = "" if st["comparisons"] else "\nПока это базовая линия (первый сбор); изменения появятся после следующего запуска."
        return f"{head}\nИзменений не обнаружено.\n{watch}{note}"
    lines = [head, watch, f"Всего событий: {len(items)}. 🔴 ставка/срок/сумма · 🟠 условия · ⚪ прочее", ""]
    for it in items[:LIMIT]:
        lines.append(f"{MARK.get(it['severity'], '')} {escape(it['text'])} <i>({_dt(it['detected_at'])})</i>")
    if len(items) > LIMIT:
        lines.append(f"… и ещё {len(items) - LIMIT}. Полный список — в отчёте (/report).")
    lines.append("\n⚠️ Данные с сайтов банков; доступность в ЛНР не подтверждена.")
    return "\n".join(lines)[:4000]
