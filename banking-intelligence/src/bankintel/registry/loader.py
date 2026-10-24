from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bankintel.db.models import Bank, Source
from bankintel.registry.schemas import RegistryConfig


def load_config(config_dir: Path) -> RegistryConfig:
    banks = yaml.safe_load((config_dir / "banks.yaml").read_text(encoding="utf-8"))
    sources = yaml.safe_load((config_dir / "sources.yaml").read_text(encoding="utf-8"))
    return RegistryConfig(banks=banks["banks"], sources=sources.get("sources", []))


async def sync_registry(session: AsyncSession, cfg: RegistryConfig) -> dict[str, int]:
    """Идемпотентно приводит БД к конфигурации. Статусы *_verified из БД не затираются,
    если человек подтвердил их вручную (в конфиге значение false)."""
    created = updated = 0
    banks: dict[str, Bank] = {}
    for bc in cfg.banks:
        bank = await session.scalar(select(Bank).where(Bank.slug == bc.slug))
        if bank is None:
            bank = Bank(slug=bc.slug, name=bc.name, website=str(bc.website), adapter=bc.adapter)
            session.add(bank)
            created += 1
        else:
            updated += 1
        bank.name, bank.website, bank.adapter = bc.name, str(bc.website), bc.adapter
        bank.is_benchmark, bank.notes = bc.is_benchmark, bc.notes
        bank.domain_verified = bank.domain_verified or bc.domain_verified
        bank.lnr_presence_verified = bank.lnr_presence_verified or bc.lnr_presence_verified
        banks[bc.slug] = bank
    await session.flush()

    for sc in cfg.sources:
        bank = banks[sc.bank]
        src = await session.scalar(select(Source).where(Source.bank_id == bank.id, Source.key == sc.key))
        if src is None:
            src = Source(bank_id=bank.id, key=sc.key, url=str(sc.url), category=sc.category)
            session.add(src)
        src.url, src.category, src.status, src.notes = str(sc.url), sc.category, sc.status, sc.notes
        src.mode = sc.mode
    await session.commit()
    return {"banks_created": created, "banks_updated": updated, "sources": len(cfg.sources)}
