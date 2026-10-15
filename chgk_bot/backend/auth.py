"""Проверка initData Telegram Mini App и выдача JWT.

initData приходит с телефона и подписана токеном бота: подделать её без токена нельзя.
Алгоритм по документации Telegram: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import jwt


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400, now: float | None = None) -> dict:
    """Возвращает {"user": {...}, "auth_date": int}; бросает AuthError, если подпись неверна или данные просрочены."""
    if not init_data or not bot_token:
        raise AuthError("Нет данных авторизации")
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received = params.pop("hash", None)
    if not received:
        raise AuthError("Нет подписи (hash)")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        raise AuthError("Подпись неверна")
    try:
        auth_date = int(params.get("auth_date", "0"))
    except ValueError:
        raise AuthError("Некорректная дата")
    if (now or time.time()) - auth_date > max_age:
        raise AuthError("Данные авторизации устарели, откройте игру заново")
    try:
        user = json.loads(params["user"])
        int(user["id"])
    except (KeyError, ValueError, TypeError):
        raise AuthError("В данных нет пользователя")
    return {"user": user, "auth_date": auth_date}


def create_token(user_id: int, name: str, secret: str, ttl: int, now: float | None = None) -> str:
    t = int(now or time.time())
    return jwt.encode({"sub": str(user_id), "name": name, "iat": t, "exp": t + ttl}, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"])
        return {"id": int(data["sub"]), "name": data.get("name", "")}
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AuthError("Сессия недействительна, откройте игру заново")


def sign_init_data(fields: dict, bot_token: str) -> str:
    """Собирает корректно подписанную initData (нужна тестам и dev-инструментам)."""
    from urllib.parse import urlencode
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})
