import pytest
from pydantic import ValidationError

from radar.llm.classifier import extract_json
from radar.llm.cost import CostTracker
from radar.llm.schemas import Event
from radar.llm.verify import inn_checksum_ok, sanitize_event

TEXT = ("ООО «Луганскуголь» (ИНН 7707083893) сократит 300 сотрудников. Директор Иван Петров заявил, "
        "что долг составляет 1,5 млрд руб.")


def ev(**kw):
    base = dict(category=3, title="t", summary="s", relevance_score=4)
    return Event(**{**base, **kw})


def test_extract_json_handles_fences_and_noise():
    assert extract_json('Вот ответ:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("нет json")


def test_event_validation_rejects_bad_category_and_score():
    with pytest.raises(ValidationError):
        ev(category=9)
    with pytest.raises(ValidationError):
        ev(relevance_score=0)


def test_inn_checksum():
    assert inn_checksum_ok("7707083893")       # Сбербанк
    assert not inn_checksum_ok("7707083894")
    assert not inn_checksum_ok("123")


def test_sanitize_keeps_facts_from_text():
    e = sanitize_event(ev(organizations=[{"name": "Луганскуголь", "inn_if_in_text": "7707083893"}],
                          amounts=["1,5 млрд руб."], employees_mentioned=300,
                          persons=[{"name": "Иван Петров", "position": "директор"}]), TEXT)
    assert e.organizations[0].inn_if_in_text == "7707083893"
    assert e.amounts == ["1,5 млрд руб."] and e.employees_mentioned == 300 and len(e.persons) == 1


def test_sanitize_drops_invented_facts():
    e = sanitize_event(ev(organizations=[{"name": "X", "inn_if_in_text": "1234567890"}],
                          amounts=["5 млрд руб."], employees_mentioned=999,
                          persons=[{"name": "Сергей Сидоров"}]), TEXT)
    assert e.organizations[0].inn_if_in_text is None
    assert e.amounts == [] and e.employees_mentioned is None and e.persons == []


def test_cost_tracker_na_without_prices_and_calc_with():
    c = CostTracker({"filter": {"input": None, "output": None}, "analyze": {"input": None, "output": None}})
    c.add("filter", 1000, 100)
    assert c.cost_usd is None and "н/д" in c.summary()
    c2 = CostTracker({"filter": {"input": 1.0, "output": 5.0}, "analyze": {"input": 3.0, "output": 15.0}})
    c2.add("filter", 1_000_000, 200_000)
    c2.add("analyze", 1_000_000, 100_000)
    assert round(c2.cost_usd, 4) == round(1 + 1 + 3 + 1.5, 4)
