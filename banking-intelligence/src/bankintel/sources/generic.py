from bankintel.sources.base import BankAdapter, ExtractedProduct, FetchedDocument, SourceRef, register_adapter


@register_adapter("generic")
class GenericAdapter(BankAdapter):
    """Заглушка этапа 1: честно ничего не извлекает.

    Банк-специфичные адаптеры (этап 2) появятся только после ручной проверки
    структуры официальных страниц.
    """

    def parse(self, source: SourceRef, doc: FetchedDocument) -> list[ExtractedProduct]:
        return []
