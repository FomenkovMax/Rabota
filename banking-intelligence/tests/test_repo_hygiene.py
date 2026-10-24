"""Репозиторий должен содержать весь исходный код: правила .gitignore не вправе скрывать модули, шаблоны, конфиги и фикстуры.
(Однажды правило `reports/` скрыло пакет `src/bankintel/reports/` — в запушенной ветке его не оказалось.)"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ["src", "tests", "config", "migrations", "certs", "docs"]
SOURCE_SUFFIXES = {".py", ".j2", ".yaml", ".yml", ".html", ".md", ".pem", ".toml", ".ini", ".mako"}


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT.parent / ".git").exists() and not (ROOT / ".git").exists(), reason="не git-checkout")
def test_no_source_file_is_ignored_by_gitignore():
    files = [str(p.relative_to(ROOT)) for d in SOURCE_DIRS for p in (ROOT / d).rglob("*")
             if p.is_file() and p.suffix in SOURCE_SUFFIXES and "__pycache__" not in p.parts]
    assert files, "ничего не найдено — тест сломан"
    out = subprocess.run(["git", "check-ignore", "--no-index", *files], cwd=ROOT, capture_output=True, text=True, check=False)
    ignored = out.stdout.split()
    assert ignored == [], f"файлы исходников скрыты .gitignore: {ignored}"


def test_report_package_and_template_exist_in_source_tree():
    assert (ROOT / "src/bankintel/reports/dataset.py").is_file()
    assert (ROOT / "src/bankintel/reports/templates/report.html.j2").is_file()
