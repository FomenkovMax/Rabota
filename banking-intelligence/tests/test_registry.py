import pytest
from pydantic import ValidationError
from sqlalchemy import select

from bankintel.config import get_settings
from bankintel.db.models import Bank, Source
from bankintel.registry.loader import load_config, sync_registry
from bankintel.registry.schemas import RegistryConfig


def _bank(slug="a", site="https://www.a-bank.ru", **kw):
    return {"slug": slug, "name": slug.upper(), "website": site, **kw}


def test_real_config_is_valid_and_has_one_benchmark():
    cfg = load_config(get_settings().config_dir)
    assert {b.slug for b in cfg.banks} >= {"sber", "psb", "vtb", "genbank", "cmr"}
    assert [b.slug for b in cfg.banks if b.is_benchmark] == ["sber"]


def test_real_config_has_no_unverified_claims():
    """Этап 1: ничего не подтверждено человеком, и конфиг не должен делать вид, что это не так."""
    cfg = load_config(get_settings().config_dir)
    assert not any(b.domain_verified or b.lnr_presence_verified for b in cfg.banks)
    assert all(s.status == "todo" for s in cfg.sources)


def test_foreign_domain_source_rejected():
    with pytest.raises(ValidationError, match="не входит в официальные домены"):
        RegistryConfig(
            banks=[_bank()],
            sources=[{"bank": "a", "key": "k", "url": "https://evil.example.com/x", "category": "deposit"}],
        )


def test_subdomain_of_official_domain_allowed():
    RegistryConfig(
        banks=[_bank()],
        sources=[{"bank": "a", "key": "k", "url": "https://promo.a-bank.ru/x", "category": "promo"}],
    )


def test_lookalike_domain_rejected():
    with pytest.raises(ValidationError):
        RegistryConfig(
            banks=[_bank()],
            sources=[{"bank": "a", "key": "k", "url": "https://fake-a-bank.ru/x", "category": "promo"}],
        )


def test_duplicate_slug_and_two_benchmarks_rejected():
    with pytest.raises(ValidationError):
        RegistryConfig(banks=[_bank("a"), _bank("a")])
    with pytest.raises(ValidationError):
        RegistryConfig(banks=[_bank("a", is_benchmark=True), _bank("b", is_benchmark=True)])


def test_unknown_bank_in_source_rejected():
    with pytest.raises(ValidationError, match="неизвестный банк"):
        RegistryConfig(banks=[_bank()], sources=[{"bank": "zzz", "key": "k", "url": "https://a-bank.ru", "category": "x"}])


async def test_sync_is_idempotent(session_factory):
    cfg = load_config(get_settings().config_dir)
    async with session_factory() as s:
        first = await sync_registry(s, cfg)
        second = await sync_registry(s, cfg)
        assert first["banks_created"] == 5 and second["banks_created"] == 0
        assert len((await s.scalars(select(Bank))).all()) == 5
        assert len((await s.scalars(select(Source))).all()) == 5


async def test_sync_keeps_manual_verification(session_factory):
    cfg = load_config(get_settings().config_dir)
    async with session_factory() as s:
        await sync_registry(s, cfg)
        bank = await s.scalar(select(Bank).where(Bank.slug == "psb"))
        bank.domain_verified = True
        await s.commit()
        await sync_registry(s, cfg)  # в конфиге по-прежнему false
        bank = await s.scalar(select(Bank).where(Bank.slug == "psb"))
        assert bank.domain_verified is True
