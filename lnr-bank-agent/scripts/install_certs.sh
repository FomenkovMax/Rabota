#!/usr/bin/env bash
# Установка корневого сертификата Минцифры (Russian Trusted Root CA) с проверкой отпечатка.
# Ставит корень в системное хранилище, в NSS DB браузера (Linux) и собирает CA-бандл для Python.
set -euo pipefail

ROOT_URL="https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"
EXPECTED_SHA256="D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="$PROJECT_DIR/data/certs"
ROOT_FILE="$CERT_DIR/russian_trusted_root_ca.pem"
BUNDLE_FILE="$CERT_DIR/ca-bundle.pem"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
# Пользователь, от имени которого работает агент (deploy.sh передаёт LNRBANK_USER=lnrbank).
TARGET_USER="${LNRBANK_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
as_user() { if [ "$TARGET_USER" = "$(id -un)" ]; then "$@"; else sudo -u "$TARGET_USER" -H --preserve-env="${PASS_ENV:-HTTPS_PROXY}" "$@"; fi; }
UV="$(as_user bash -lc 'command -v uv' || true)"; UV="${UV:-$TARGET_HOME/.local/bin/uv}"

mkdir -p "$CERT_DIR"
echo "→ Скачиваю корень Минцифры с $ROOT_URL"
curl -fsSL "$ROOT_URL" -o "$ROOT_FILE.tmp"

ACTUAL="$(openssl x509 -in "$ROOT_FILE.tmp" -noout -fingerprint -sha256 | cut -d= -f2)"
if [ "$ACTUAL" != "$EXPECTED_SHA256" ]; then
  rm -f "$ROOT_FILE.tmp"
  echo "✗ Отпечаток не совпал: $ACTUAL. Ничего не установлено." >&2
  exit 1
fi
mv "$ROOT_FILE.tmp" "$ROOT_FILE"
echo "✓ fingerprint OK"

case "$(uname -s)" in
  Linux)
    $SUDO cp "$ROOT_FILE" /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
    $SUDO update-ca-certificates >/dev/null
    echo "✓ системное хранилище"
    if ! command -v certutil >/dev/null; then
      $SUDO apt-get install -y -q libnss3-tools >/dev/null
    fi
    NSS="$TARGET_HOME/.pki/nssdb"
    as_user mkdir -p "$NSS"
    [ -f "$NSS/cert9.db" ] || as_user certutil -d "sql:$NSS" -N --empty-password
    as_user certutil -d "sql:$NSS" -D -n "Russian Trusted Root CA" 2>/dev/null || true
    as_user certutil -d "sql:$NSS" -A -t "C,," -n "Russian Trusted Root CA" -i "$ROOT_FILE"
    echo "✓ хранилище браузера (NSS)"
    ;;
  Darwin)
    $SUDO security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$ROOT_FILE"
    echo "✓ системная связка ключей macOS (её использует и Chromium)"
    ;;
  *) echo "✗ Неподдерживаемая ОС $(uname -s)" >&2; exit 1 ;;
esac

CERTIFI="$(cd "$PROJECT_DIR" && as_user "$UV" run --quiet --no-dev python -c 'import certifi; print(certifi.where())')"
cat "$CERTIFI" "$ROOT_FILE" > "$BUNDLE_FILE"
[ "$TARGET_USER" = "$(id -un)" ] || chown -R "$TARGET_USER": "$CERT_DIR"
echo "✓ CA-бандл для Python: $BUNDLE_FILE"
