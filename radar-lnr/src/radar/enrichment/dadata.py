"""DaData (официальный API подсказок по организациям). Нужны DADATA_API_KEY (токен)."""
from __future__ import annotations

import httpx

from .base import Adapter, AdapterError, OrgCard

BASE = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"
STATUS_RU = {"ACTIVE": "Действует", "LIQUIDATING": "Ликвидируется", "LIQUIDATED": "Ликвидирована",
             "BANKRUPT": "Банкротство", "REORGANIZING": "Реорганизация"}


def parse_party(s: dict) -> OrgCard:
    """Один элемент suggestions из ответа DaData -> OrgCard. Только то, что реально пришло."""
    d = s.get("data") or {}
    mgmt = d.get("management") or {}
    fio = d.get("fio") or {}                      # у ИП руководитель = сам предприниматель
    director = mgmt.get("name") or " ".join(x for x in (fio.get("surname"), fio.get("name"), fio.get("patronymic")) if x) or None
    founders = []
    for f in d.get("founders") or []:
        n = f.get("name") or " ".join(x for x in ((f.get("fio") or {}).get(k) for k in ("surname", "name", "patronymic")) if x)
        if n:
            founders.append(n)
    name = d.get("name") or {}
    emp = d.get("employee_count")
    st = (d.get("state") or {}).get("status")
    return OrgCard(
        inn=d.get("inn"), ogrn=d.get("ogrn"), kpp=d.get("kpp"),
        name_full=name.get("full_with_opf") or s.get("value"), name_short=name.get("short_with_opf"),
        okved=d.get("okved"), address=(d.get("address") or {}).get("value"),
        director=director, director_post=mgmt.get("post") or ("Индивидуальный предприниматель" if fio and not mgmt else None),
        founders=founders, employees=int(emp) if isinstance(emp, (int, float)) else None,
        status=STATUS_RU.get(st, st),
        phones=[p["value"] for p in d.get("phones") or [] if p.get("value")],
        emails=[e["value"] for e in d.get("emails") or [] if e.get("value")],
        source="dadata")


class DaDataAdapter(Adapter):
    name = "dadata"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=20)
        self.headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json",
                        "Accept": "application/json"}

    async def _post(self, path: str, body: dict) -> list[dict]:
        try:
            r = await self.client.post(f"{BASE}/{path}", json=body, headers=self.headers)
        except httpx.HTTPError as e:
            raise AdapterError(f"DaData недоступна: {type(e).__name__}") from None
        if r.status_code in (401, 403):
            raise AdapterError("DaData: неверный DADATA_API_KEY или нет прав")
        if r.status_code == 429:
            raise AdapterError("DaData: превышен лимит запросов, повтори позже")
        if r.status_code != 200:
            raise AdapterError(f"DaData: HTTP {r.status_code}")
        return r.json().get("suggestions") or []

    async def by_inn(self, inn: str) -> list[OrgCard]:
        items = await self._post("findById/party", {"query": inn, "count": 5})
        cards = [parse_party(s) for s in items]
        # findById отдаёт и филиалы — головную организацию ставим первой
        main = [c for c, s in zip(cards, items) if (s.get("data") or {}).get("branch_type") != "BRANCH"]
        return main or cards

    async def by_name(self, name: str, region: str | None = None) -> list[OrgCard]:
        body = {"query": name, "count": 5}
        if region:
            body["locations"] = [{"region": region}]
        return [parse_party(s) for s in await self._post("suggest/party", body)]
