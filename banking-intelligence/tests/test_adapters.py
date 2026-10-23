import pytest

from bankintel.domain.enums import CollectionStatus, FetchOutcome
from bankintel.sources import get_adapter
from bankintel.sources.base import FetchDiagnostic, FetchedDocument, SourceRef

SRC_A = SourceRef("a", "https://www.a-bank.ru/a", "deposit")
SRC_B = SourceRef("b", "https://www.a-bank.ru/b", "deposit")


class FakeFetcher:
    def __init__(self, failing: set[str] = frozenset()):
        self.failing = failing

    async def fetch(self, source):
        if source.key in self.failing:
            return None, FetchDiagnostic(source.key, source.url, FetchOutcome.HTTP_ERROR, 503, "boom")
        return FetchedDocument(source.url, b"<html/>"), FetchDiagnostic(source.key, source.url, FetchOutcome.OK, 200)


def test_generic_adapter_registered_and_extracts_nothing():
    cls = get_adapter("generic")
    assert cls("sber").parse(SRC_A, FetchedDocument(SRC_A.url, b"x")) == []


def test_unknown_adapter():
    with pytest.raises(KeyError):
        get_adapter("nope")


async def test_no_sources_is_failed_not_ok():
    res = await get_adapter("generic")("sber", FakeFetcher()).collect([])
    assert res.status == CollectionStatus.FAILED


async def test_no_fetcher_is_not_implemented():
    res = await get_adapter("generic")("sber").collect([SRC_A])
    assert res.status == CollectionStatus.NOT_IMPLEMENTED


async def test_all_ok():
    res = await get_adapter("generic")("sber", FakeFetcher()).collect([SRC_A, SRC_B])
    assert res.status == CollectionStatus.OK and len(res.documents) == 2


async def test_partial_keeps_diagnostics():
    res = await get_adapter("generic")("sber", FakeFetcher({"b"})).collect([SRC_A, SRC_B])
    assert res.status == CollectionStatus.PARTIAL
    assert len(res.diagnostics) == 2
    assert any("http_error" in m for m in res.messages)


async def test_all_failed():
    res = await get_adapter("generic")("sber", FakeFetcher({"a", "b"})).collect([SRC_A, SRC_B])
    assert res.status == CollectionStatus.FAILED and not res.documents
