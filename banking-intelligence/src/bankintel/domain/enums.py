from enum import StrEnum


class ProductCategory(StrEnum):
    DEPOSIT = "deposit"          # срочный вклад
    SAVINGS = "savings"          # накопительный счёт
    PROMO = "promo"              # акция / специальное предложение


class AvailabilityStatus(StrEnum):
    """Доступность продукта в ЛНР. Общероссийская доступность НЕ равна CONFIRMED."""

    CONFIRMED = "confirmed"          # есть явное подтверждение в источнике (цитата/страница)
    UNAVAILABLE = "unavailable"      # источник явно исключает ЛНР
    NOT_CONFIRMED = "not_confirmed"  # продукт найден, упоминания ЛНР нет
    UNKNOWN = "unknown"              # не проверялось или источник недоступен


class CollectionStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_IMPLEMENTED = "not_implemented"


class FetchOutcome(StrEnum):
    OK = "ok"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    TLS_ERROR = "tls_error"          # сертификат не прошёл проверку: НЕ отключаем verify
    TOO_LARGE = "too_large"
    ROBOTS_DISALLOWED = "robots_disallowed"
    BLOCKED = "blocked"              # капча/антибот: фиксируем и НЕ обходим


class SourceStatus(StrEnum):
    TODO = "todo"            # URL ещё не определён/не проверен человеком
    ACTIVE = "active"
    DISABLED = "disabled"


class ChangeType(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    REMOVED = "removed"
