"""Калькулятор на странице: регион ЛНР, все цели из списка, ставка (сбор 28.10.2026)."""

import functools
import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.banks import calculator

# Похоже на калькулятор ипотеки Сбера: поле региона с подсказками, включённая
# по умолчанию скидка «Получаю зарплату», свой выпадающий список цели и панель
# результата справа. Вторичка в ЛНР недоступна, новостройка — 18,9 % (без
# зарплатной скидки; с ней — 17,9 %).
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Ипотека</title></head><body>
<h1>Ипотека на вторичное жильё</h1>
<header><div>Программа для семей с детьми</div><a href="#">Партнерская программа</a>
<ul><li>Дебетовые карты</li></ul></header>
<div style="display:flex">
<div id="calc">
  <div><span>Регион покупки недвижимости</span><input id="reg" value="Москва"></div>
  <ul id="sug" role="listbox"></ul>
  <div><span>Цель кредита</span><div id="goal" role="combobox" tabindex="0">Квартира на вторичном рынке</div></div>
  <ul id="opts" role="listbox" style="display:none">
    <li role="option">Квартира на вторичном рынке</li><li role="option">Квартира в новостройке</li>
  </ul>
  <div id="progbox" style="display:none"><span>Программа</span><div id="prog" role="combobox" tabindex="0">Стандартная</div></div>
  <ul id="popts" role="listbox" style="display:none">
    <li role="option">Стандартная</li><li role="option">Региональная</li>
  </ul>
  <label><span>Получаю зарплату на Сбер</span><input id="sal" type="checkbox" checked></label>
</div>
<div id="res"></div></div>
<script>
const st = {region: 'Москва', goal: 'Квартира на вторичном рынке', prog: 'Стандартная'};
const reg = document.getElementById('reg'), sug = document.getElementById('sug');
reg.addEventListener('input', () => { sug.innerHTML = reg.value.length > 2
  ? '<li role="option">Луганская Народная Республика, Луганск</li>' : ''; });
sug.addEventListener('click', e => { st.region = e.target.innerText; reg.value = st.region;
  sug.innerHTML = ''; draw(); });
const opts = document.getElementById('opts'), goal = document.getElementById('goal');
goal.addEventListener('click', () => { opts.style.display = 'block'; });
opts.addEventListener('click', e => { st.goal = e.target.innerText; goal.innerText = st.goal;
  opts.style.display = 'none';
  document.getElementById('progbox').style.display = st.goal.includes('новострой') ? 'block' : 'none';
  draw(); });
const popts = document.getElementById('popts'), prog = document.getElementById('prog');
prog.addEventListener('click', () => { popts.style.display = 'block'; });
popts.addEventListener('click', e => { st.prog = e.target.innerText; prog.innerText = st.prog;
  popts.style.display = 'none'; draw(); });
document.getElementById('sal').addEventListener('change', draw);
function draw() {
  const res = document.getElementById('res');
  if (st.region.startsWith('Луганская') && st.goal.includes('вторичн')) {
    res.innerText = 'Программа недоступна в вашем регионе'; return; }
  let base = st.region.startsWith('Луганская') ? 18.9 : 21.9;
  if (st.goal.includes('новострой') && st.prog === 'Региональная') base = 3.0;
  const r = base - (document.getElementById('sal').checked ? 1 : 0);
  res.innerText = 'Ставка\\n' + r.toFixed(1).replace('.', ',') + '%\\nЕжемесячный платёж\\n95 000 ₽';
}
draw();
</script></body></html>"""


def test_read_result():
    assert calculator.read_result("Ставка\n18,9%\nЕжемесячный платёж\n95 000 ₽") == {
        "available": True, "rate": 18.9, "payment": 95000, "note": ""}
    assert calculator.read_result("Программа недоступна в вашем регионе")["available"] is False


def test_explore_sets_region_turns_off_salary_and_reads_every_goal(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    from src.banks.browser import BrowserSettings, browser_session

    settings = BrowserSettings(settle_ms=300, pause_s=0,
                               calculator_region="Луганская Народная Республика, Луганск")
    try:
        with browser_session(settings) as session:
            data = session.inspect(f"http://127.0.0.1:{server.server_port}/index.html")
    except Exception as exc:                        # noqa: BLE001
        pytest.skip(f"браузер недоступен: {exc}")
    finally:
        server.shutdown()
    calc = data["calculator"]
    assert calc["region"].startswith("Луганская Народная Республика")
    assert calc["discounts_off"]
    by_goal = {o["option"]: o for o in calc["options"]}
    assert by_goal["Квартира на вторичном рынке"]["available"] is False
    assert by_goal["Квартира в новостройке"]["rate"] == 18.9
    assert by_goal["Квартира в новостройке → Стандартная"]["rate"] == 18.9
    # Зарплатная скидка у льготной программы тоже выключена: 3,0, а не 2,0.
    assert by_goal["Квартира в новостройке → Региональная"]["rate"] == 3.0
    assert calc["complete"] is True
    assert "недоступно в регионе" in calculator.summary(calc)


def test_unavailable_goal_marks_program_products():
    from src import market
    from src.banks import crawl_adapter as crawl
    from src.psb.parser import Product
    probe = Product(bank="Сбер", title="Квартира на вторичном рынке", category="Ипотека")
    assert crawl.market_program(probe) == "Вторичное жильё"
    assert crawl.market_program(Product(title="Другое", category="Ипотека")) == ""
    second = Product(bank="Сбер", title="Ипотека на вторичное жильё", category="Ипотека")
    family = Product(bank="Сбер", title="Семейная ипотека", category="Ипотека")
    crawl.mark_blocked([second, family], {"Вторичное жильё": "калькулятор: недоступно"})
    assert second.terms[market.REGION_KEY] == "калькулятор: недоступно"
    assert market.REGION_KEY not in family.terms


def test_calculator_inside_iframe(tmp_path, monkeypatch):
    """Калькулятор во встроенном окне виджета — тоже находится."""
    (tmp_path / "calc.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>Ипотека</title></head>'
        '<body><h1>Ипотека</h1><iframe src="calc.html" width="1200" height="900"></iframe>'
        '</body></html>', encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    from src.banks.browser import BrowserSettings, browser_session

    settings = BrowserSettings(settle_ms=800, pause_s=0,
                               calculator_region="Луганская Народная Республика, Луганск")
    try:
        with browser_session(settings) as session:
            data = session.inspect(f"http://127.0.0.1:{server.server_port}/index.html")
    except Exception as exc:                        # noqa: BLE001
        pytest.skip(f"браузер недоступен: {exc}")
    finally:
        server.shutdown()
    calc = data["calculator"]
    assert calc["frame"].endswith("/calc.html")
    assert {o["option"]: o for o in calc["options"]}["Квартира в новостройке"]["rate"] == 18.9
