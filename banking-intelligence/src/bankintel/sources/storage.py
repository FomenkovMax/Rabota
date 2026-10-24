import hashlib
import mimetypes
from pathlib import Path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_raw(root: Path, bank_slug: str, content: bytes, content_type: str | None) -> tuple[str, str]:
    """Сохраняет документ по хешу (дубликаты не плодятся). Возвращает (sha256, путь относительно root)."""
    digest = sha256_hex(content)
    ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".bin"
    rel = Path(bank_slug) / f"{digest}{ext}"
    target = root / rel
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return digest, str(rel)
