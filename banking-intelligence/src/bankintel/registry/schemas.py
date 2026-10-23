from urllib.parse import urlparse

from pydantic import BaseModel, HttpUrl, model_validator


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


class BankConfig(BaseModel):
    slug: str
    name: str
    website: HttpUrl
    adapter: str = "generic"
    is_benchmark: bool = False
    domain_verified: bool = False
    lnr_presence_verified: bool = False
    extra_domains: list[str] = []
    notes: str | None = None

    @property
    def official_hosts(self) -> set[str]:
        return {_host(str(self.website)), *(d.lower().removeprefix("www.") for d in self.extra_domains)}


class SourceConfig(BaseModel):
    bank: str
    key: str
    url: HttpUrl
    category: str
    status: str = "todo"
    notes: str | None = None


class RegistryConfig(BaseModel):
    banks: list[BankConfig]
    sources: list[SourceConfig] = []

    @model_validator(mode="after")
    def _validate(self):
        slugs = [b.slug for b in self.banks]
        if len(slugs) != len(set(slugs)):
            raise ValueError("Повторяющиеся slug банков")
        if sum(b.is_benchmark for b in self.banks) > 1:
            raise ValueError("Эталонным (is_benchmark) может быть только один банк")
        by_slug = {b.slug: b for b in self.banks}
        seen = set()
        for s in self.sources:
            bank = by_slug.get(s.bank)
            if bank is None:
                raise ValueError(f"Источник {s.key}: неизвестный банк {s.bank!r}")
            if (s.bank, s.key) in seen:
                raise ValueError(f"Повторяющийся источник {s.bank}/{s.key}")
            seen.add((s.bank, s.key))
            host = _host(str(s.url))
            if not any(host == h or host.endswith("." + h) for h in bank.official_hosts):
                raise ValueError(
                    f"Источник {s.bank}/{s.key}: домен {host} не входит в официальные домены банка"
                )
        return self
