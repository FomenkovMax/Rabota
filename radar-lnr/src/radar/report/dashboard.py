"""Один HTML-файл: таблица с фильтрами, карточки, итог потенциала. Данные встроены как JSON.

Безопасность: тексты новостей — недоверенные, поэтому в браузере выводим только через textContent,
а ссылки пропускаем лишь если они начинаются с https://t.me/.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..finance import FORMULA
from ..llm.schemas import CATEGORIES
from .excel import district_of

TEMPLATE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Радар ЛНР — __PERIOD__</title>
<style>
:root{--bg:#f6f8f7;--card:#fff;--ink:#17201b;--mut:#5d6b63;--line:#dfe6e2;--acc:#21a038;--warn:#b26a00}
@media(prefers-color-scheme:dark){:root{--bg:#121714;--card:#1b231e;--ink:#e8efea;--mut:#9aa9a0;--line:#2b362f;--acc:#3ccb5a;--warn:#e0a040}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}h1{margin:0 0 4px;font-size:22px}.mut{color:var(--mut)}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:150px}
.kpi b{display:block;font-size:20px}.bar{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
select,input{padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}.card h3{margin:.2em 0;font-size:16px}
.tag{display:inline-block;padding:2px 8px;border-radius:99px;border:1px solid var(--line);font-size:12px;margin-right:4px}
.score{color:var(--acc);font-weight:700}table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;font-size:14px}
th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{cursor:pointer;background:var(--bg)}
.wrap{overflow-x:auto;margin-top:16px}details{margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
a{color:var(--acc)}.nd{color:var(--mut)}.est{color:var(--warn)}
</style></head><body><main>
<h1>📡 Радар ЛНР</h1><div class="mut" id="period"></div>
<div class="kpis"><div class="kpi"><span class="mut">Событий</span><b id="k-n">0</b></div>
<div class="kpi"><span class="mut">≈ Суммарный потенциал / год</span><b id="k-p" class="est">н/д</b></div>
<div class="kpi"><span class="mut">События с оценкой</span><b id="k-w">0</b></div></div>
<div class="bar"><select id="f-cat"></select><select id="f-dist"></select>
<select id="f-score"><option value="1">Оценка ≥ 1</option><option value="2">≥ 2</option><option value="3">≥ 3</option><option value="4">≥ 4</option></select>
<input id="f-q" placeholder="Поиск по тексту"></div>
<div class="cards" id="cards"></div>
<div class="wrap"><table><thead><tr id="thead"></tr></thead><tbody id="tbody"></tbody></table></div>
<details><summary>Как считается ≈ оценка</summary><p id="formula"></p>
<p class="mut">Оценка ориентировочная; если численность не указана в источнике, пишем «н/д». Зарплаты по отраслям и коэффициенты — заглушки до уточнения.</p></details>
</main><script id="data" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const fmt=n=>n==null?'н/д':n>=1e6?(n/1e6).toFixed(1).replace('.',',')+' млн ₽':n>=1e3?Math.round(n/1e3)+' тыс. ₽':Math.round(n)+' ₽';
function el(tag,txt,cls){const e=document.createElement(tag);if(txt!=null)e.textContent=txt;if(cls)e.className=cls;return e}
function link(u,i){if(!/^https:\\/\\/t\\.me\\//.test(u))return null;const a=el('a','источник '+i);a.href=u;a.target='_blank';a.rel='noopener noreferrer';return a}
$('period').textContent=D.period;$('formula').textContent=D.formula;
const cats=[...new Set(D.events.map(e=>e.cat))],dists=[...new Set(D.events.map(e=>e.district))].sort();
$('f-cat').append(new Option('Все категории',''));cats.forEach(c=>$('f-cat').append(new Option(c,c)));
$('f-dist').append(new Option('Все районы',''));dists.forEach(c=>$('f-dist').append(new Option(c,c)));
const COLS=[['score','Оц.'],['cat','Категория'],['title','Событие'],['org','Организация / ИНН'],['district','Район'],['lpr','ЛПР'],['potential','≈ Потенциал/год']];
let sortKey='score',sortDir=-1;
COLS.forEach(([k,t])=>{const th=el('th',t);th.onclick=()=>{sortDir=sortKey==k?-sortDir:-1;sortKey=k;render()};$('thead').append(th)});
function render(){
 const q=$('f-q').value.toLowerCase(),c=$('f-cat').value,d=$('f-dist').value,s=+$('f-score').value;
 const rows=D.events.filter(e=>e.score>=s&&(!c||e.cat==c)&&(!d||e.district==d)&&(!q||(e.title+e.summary+e.org).toLowerCase().includes(q)))
  .sort((a,b)=>{const x=a[sortKey],y=b[sortKey];return (x==null)-(y==null)||(x>y?1:x<y?-1:0)*sortDir});
 $('k-n').textContent=rows.length;
 const sum=rows.reduce((a,e)=>a+(e.potential||0),0),w=rows.filter(e=>e.potential!=null).length;
 $('k-p').textContent=w?'≈ '+fmt(sum):'н/д';$('k-w').textContent=w;
 const cards=$('cards'),tb=$('tbody');cards.replaceChildren();tb.replaceChildren();
 rows.forEach(e=>{
  const k=el('div',null,'card');
  k.append(el('span','⭐'+e.score,'tag score'),el('span',e.cat,'tag'),el('span',e.district,'tag'));
  k.append(el('h3',e.title),el('div',e.summary));
  k.append(el('div','🏷 '+e.org+' (ИНН '+e.inn+')','mut'),el('div','👤 '+(e.lpr||'н/д'),'mut'));
  k.append(el('div','💵 '+e.effect,e.potential==null?'nd':'est'));
  if(e.opportunity)k.append(el('div','🎯 '+e.opportunity));
  const l=el('div');e.urls.forEach((u,i)=>{const a=link(u,i+1);if(a){l.append(a,' ')}});k.append(l);cards.append(k);
  const tr=el('tr');[e.score,e.cat,e.title,e.org+' / '+e.inn,e.district,e.lpr||'н/д',e.potential==null?'н/д':'≈ '+fmt(e.potential)].forEach(v=>tr.append(el('td',v)));tb.append(tr)});
}
['f-cat','f-dist','f-score'].forEach(i=>$(i).onchange=render);$('f-q').oninput=render;render();
</script></body></html>"""


def _row(ev: dict, districts: dict[str, str]) -> dict:
    enr = ev.get("enriched") or {}
    card = enr.get("card") if enr.get("status") == "found" else None
    org = (ev.get("organizations") or [{}])[0]
    persons = ev.get("persons") or []
    inn = (card or {}).get("inn") or org.get("inn_if_in_text") or ("требует проверки" if enr.get("status") == "needs_review" else "н/д")
    lpr = (card or {}).get("director") or (persons[0]["name"] if persons else None)
    fin = ev.get("finance") or {}
    return {"score": ev["relevance_score"], "cat": f"{CATEGORIES[ev['category']][0]} {CATEGORIES[ev['category']][1]}",
            "title": ev["title"], "summary": ev["summary"], "org": org.get("name") or "н/д", "inn": inn,
            "district": district_of(ev, districts), "lpr": lpr, "potential": fin.get("potential_year"),
            "effect": ev.get("fin_effect_text") or "н/д", "opportunity": ev.get("business_opportunity"),
            "urls": ev.get("source_urls") or []}


def render_dashboard(events: list[dict], since: datetime, until: datetime, districts: dict[str, str] | None = None,
                     tz: str = "Europe/Moscow") -> str:
    z = ZoneInfo(tz)
    period = f"Период: {since.astimezone(z):%d.%m.%Y %H:%M} – {until.astimezone(z):%d.%m.%Y %H:%M} (МСК)"
    data = {"period": period, "formula": FORMULA, "events": [_row(e, districts or {}) for e in events]}
    # </ внутри JSON закрыл бы <script> — экранируем
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__PERIOD__", period.replace("<", "")).replace("__DATA__", blob)
