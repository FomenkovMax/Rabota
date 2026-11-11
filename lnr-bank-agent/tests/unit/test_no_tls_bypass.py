import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
FORBIDDEN = re.compile(
    r"verify\s*=\s*False|verify_ssl_certs\s*=\s*False|ignore_https_errors\s*=\s*True"
)


def test_no_tls_verification_bypass():
    hits = [
        f"{p}:{i}"
        for p in SRC.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert hits == []


def test_install_script_pins_same_fingerprint():
    from lnrbank.net.tls import MINTSIFRY_ROOT_SHA256

    script = (SRC.parent / "scripts" / "install_certs.sh").read_text(encoding="utf-8")
    assert f'EXPECTED_SHA256="{MINTSIFRY_ROOT_SHA256}"' in script
