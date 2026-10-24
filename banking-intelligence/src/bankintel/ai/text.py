from bs4 import BeautifulSoup

NOISE = ("script", "style", "noscript", "svg", "iframe", "nav", "footer", "form")


def html_to_text(content: bytes, max_chars: int) -> tuple[str, bool]:
    """Чистый текст страницы (без скриптов, меню, подвала). Возвращает (текст, обрезан_ли).
    Проверка цитат идёт по ТОМУ ЖЕ тексту, который отправляется модели."""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(NOISE):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).replace(" ", " ").split())
    return (text[:max_chars], True) if len(text) > max_chars else (text, False)
