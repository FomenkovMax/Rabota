"""Пакетный ручной импорт. Данные синтетические (тестовые)."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from bankintel.db.models import Bank, Document, Source
from bankintel.sources.manual_batch import (
    MANIFEST_NAME,
    ManifestError,
    import_directory,
    load_manifest,
    write_manifest_template,
)

HOSTS = {"sberbank.ru"}
URL_A = "https://www.sberbank.ru/ru/person/synthetic-a"
URL_B = "https://www.sberbank.ru/ru/person/synthetic-b"
HEAD = "captured_at: 2026-10-24T12:00+03:00\ncategory: deposit\npages:\n"


def _write(d, name, body=b"<html>synthetic page</html>"):
    (d / name).write_bytes(body)


def _manifest(d, text):
    (d / MANIFEST_NAME).write_text(text, encoding="utf-8")
    return load_manifest(d / MANIFEST_NAME)


async def _run(seeded, tmp_path, manifest, **kw):
    async with seeded() as s:
        bank = await s.scalar(select(Bank).where(Bank.slug == "sber"))
        return await import_directory(s, bank, tmp_path, manifest, official_hosts=HOSTS, raw_root=tmp_path / "raw", **kw)


async def _docs(seeded):
    async with seeded() as s:
        return await s.scalar(select(func.count(Document.id)))


def _statuses(rep):
    return {r.file: r.status for r in rep.results}


async def test_imports_all_pages_with_manual_origin(seeded, tmp_path):
    _write(tmp_path, "a.html")
    _write(tmp_path, "b.html", b"<html>other synthetic page</html>")
    m = _manifest(tmp_path, HEAD + f"  - file: a.html\n    url: {URL_A}\n  - file: b.html\n    url: {URL_B}\n    category: savings\n    source_key: acc\n")
    rep = await _run(seeded, tmp_path, m)
    assert _statuses(rep) == {"a.html": "imported", "b.html": "imported"} and rep.rejected == 0
    assert {p.source_key for p in rep.new_sources} == {"a", "acc"}
    async with seeded() as s:
        docs = (await s.scalars(select(Document))).all()
        assert {d.origin for d in docs} == {"manual_import"}
        assert {d.fetched_at.replace(tzinfo=UTC) for d in docs} == {datetime(2026, 10, 24, 9, 0, tzinfo=UTC)}
        src = await s.scalar(select(Source).where(Source.key == "acc"))
        assert src.category == "savings" and src.mode == "manual"


async def test_second_run_is_idempotent_and_changed_file_is_new_version(seeded, tmp_path):
    _write(tmp_path, "a.html")
    m = _manifest(tmp_path, HEAD + f"  - file: a.html\n    url: {URL_A}\n")
    await _run(seeded, tmp_path, m)
    rep = await _run(seeded, tmp_path, m)
    assert _statuses(rep) == {"a.html": "unchanged"} and rep.new_sources == []
    assert await _docs(seeded) == 1
    _write(tmp_path, "a.html", b"<html>synthetic page, edited</html>")
    rep = await _run(seeded, tmp_path, m)
    assert _statuses(rep) == {"a.html": "imported"} and rep.new_sources == []
    assert await _docs(seeded) == 2


async def test_url_taken_from_chrome_saved_from_comment(seeded, tmp_path):
    _write(tmp_path, "a.html", f"<!-- saved from url=(0052){URL_A} -->\n<html>x</html>".encode())
    rep = await _run(seeded, tmp_path, _manifest(tmp_path, HEAD + "  - file: a.html\n"))
    assert _statuses(rep) == {"a.html": "imported"}
    async with seeded() as s:
        assert (await s.scalar(select(Document.url))) == URL_A


@pytest.mark.parametrize(
    "body,page,msg",
    [
        ("<html>{code:'user_blocked'} Возникла проблема при открытии сайта</html>".encode(), f"url: {URL_A}", "блокировки"),
        (b"<html>x</html>", "url: https://evil.example.com/x", "официальные домены"),
        (b"", f"url: {URL_A}", "пустой"),
        (b"<html>x</html>", "url: ЗАПОЛНИТЕ", "не указан url"),
        (b"<html>x</html>", "", "не указан url"),
    ],
)
async def test_bad_pages_are_rejected_without_blocking_good_ones(seeded, tmp_path, body, page, msg):
    _write(tmp_path, "bad.html", body)
    _write(tmp_path, "good.html")
    m = _manifest(tmp_path, HEAD + f"  - file: bad.html\n    {page}\n  - file: good.html\n    url: {URL_B}\n")
    rep = await _run(seeded, tmp_path, m)
    st = _statuses(rep)
    assert st == {"bad.html": "rejected", "good.html": "imported"}
    assert msg in next(r.detail for r in rep.results if r.file == "bad.html")
    assert await _docs(seeded) == 1


@pytest.mark.parametrize(
    "head,entry,msg",
    [
        ("captured_at: 2026-10-24T12:00\ncategory: deposit\npages:\n", f"file: a.html\n    url: {URL_A}", "часового пояса"),
        ("category: deposit\npages:\n", f"file: a.html\n    url: {URL_A}", "не указана дата"),
        ("captured_at: вчера\ncategory: deposit\npages:\n", f"file: a.html\n    url: {URL_A}", "формате ISO"),
        ("captured_at: 2026-10-24T12:00+03:00\npages:\n", f"file: a.html\n    url: {URL_A}", "category"),
        (HEAD, f"file: ../outside.html\n    url: {URL_A}", "внутри папки"),
        (HEAD, f"file: missing.html\n    url: {URL_A}", "не найден"),
        (HEAD, f"file: a.html\n    url: {URL_A}\n    source_key: Bad Key!", "недопустим"),
    ],
)
async def test_manifest_entry_errors(seeded, tmp_path, head, entry, msg):
    (tmp_path.parent / "outside.html").write_bytes(b"<html>x</html>")
    _write(tmp_path, "a.html")
    rep = await _run(seeded, tmp_path, _manifest(tmp_path, head + f"  - {entry}\n"))
    (res,) = rep.results
    assert res.status == "rejected" and msg in res.detail
    assert await _docs(seeded) == 0


async def test_duplicate_source_key_and_changed_url_rejected(seeded, tmp_path):
    _write(tmp_path, "a.html")
    _write(tmp_path, "b.html", b"<html>second</html>")
    m = _manifest(tmp_path, HEAD + f"  - file: a.html\n    url: {URL_A}\n    source_key: k\n  - file: b.html\n    url: {URL_B}\n    source_key: k\n")
    rep = await _run(seeded, tmp_path, m)
    assert _statuses(rep) == {"a.html": "imported", "b.html": "rejected"}
    # тот же ключ, другой URL уже после импорта
    m2 = _manifest(tmp_path, HEAD + f"  - file: b.html\n    url: {URL_B}\n    source_key: k\n")
    rep = await _run(seeded, tmp_path, m2)
    assert "другому URL" in rep.results[0].detail and rep.results[0].status == "rejected"


async def test_unlisted_files_are_reported_not_imported(seeded, tmp_path):
    _write(tmp_path, "a.html")
    _write(tmp_path, "forgotten.html")
    rep = await _run(seeded, tmp_path, _manifest(tmp_path, HEAD + f"  - file: a.html\n    url: {URL_A}\n"))
    assert rep.unlisted == ["forgotten.html"] and await _docs(seeded) == 1


async def test_dry_run_checks_but_writes_nothing(seeded, tmp_path):
    _write(tmp_path, "a.html")
    _write(tmp_path, "bad.html", b"<html>{code:'user_blocked'}</html>")
    m = _manifest(tmp_path, HEAD + f"  - file: a.html\n    url: {URL_A}\n  - file: bad.html\n    url: {URL_B}\n")
    rep = await _run(seeded, tmp_path, m, dry_run=True)
    assert _statuses(rep) == {"a.html": "imported", "bad.html": "rejected"}
    assert await _docs(seeded) == 0 and not (tmp_path / "raw").exists()
    async with seeded() as s:
        assert await s.scalar(select(Source).where(Source.key == "a")) is None


async def test_mtime_uses_file_modification_time(seeded, tmp_path):
    _write(tmp_path, "a.html")
    stamp = datetime(2026, 10, 20, 8, 30, tzinfo=UTC).timestamp()
    os.utime(tmp_path / "a.html", (stamp, stamp))
    m = _manifest(tmp_path, f"captured_at: mtime\ncategory: promo\npages:\n  - file: a.html\n    url: {URL_A}\n")
    await _run(seeded, tmp_path, m)
    async with seeded() as s:
        assert (await s.scalar(select(Document.fetched_at))).replace(tzinfo=UTC) == datetime(2026, 10, 20, 8, 30, tzinfo=UTC)


def test_unknown_manifest_field_is_an_error(tmp_path):
    (tmp_path / MANIFEST_NAME).write_text("captured_at: mtime\npagez: []\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="некорректен"):
        load_manifest(tmp_path / MANIFEST_NAME)
    with pytest.raises(ManifestError, match="не найден"):
        load_manifest(tmp_path / "nope.yaml")


def test_template_prefills_url_and_never_overwrites(tmp_path):
    _write(tmp_path, "a.html", f"<!-- saved from url=(0052){URL_A} -->\n<html>x</html>".encode())
    _write(tmp_path, "b.html")
    _write(tmp_path, "notes.txt", b"ignored")
    path, n = write_manifest_template(tmp_path, category="savings")
    text = path.read_text(encoding="utf-8")
    assert n == 2 and f"url: {URL_A}" in text and "ЗАПОЛНИТЕ" in text and "category: savings" in text
    assert load_manifest(path).pages[0].file == "a.html"
    with pytest.raises(ManifestError, match="уже существует"):
        write_manifest_template(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ManifestError, match="нет .html"):
        write_manifest_template(empty)
