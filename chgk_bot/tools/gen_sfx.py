"""Синтез звуков игры (авторские, без лицензионных вопросов): python tools/gen_sfx.py
Кладёт sfx.spin / sfx.tick / sfx.timer10 / sfx.ok / sfx.fail в webapp/public/assets/ (mp3). Нужен numpy и ffmpeg."""
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "webapp" / "public" / "assets"
rng = np.random.default_rng(7)


def t(d):
    return np.linspace(0, d, int(SR * d), endpoint=False)


def env(n, attack=0.005, decay=6.0):
    x = np.arange(n) / SR
    return np.minimum(1, x / attack) * np.exp(-decay * x)


def bell(freq, d, decay=5.0):
    x = t(d)
    s = np.sin(2 * np.pi * freq * x) + 0.4 * np.sin(2 * np.pi * freq * 2.01 * x) + 0.15 * np.sin(2 * np.pi * freq * 3.02 * x)
    return s * env(len(x), 0.004, decay)


def click(d=0.03, f=1800, noise=0.5):
    x = t(d)
    s = np.sin(2 * np.pi * f * x) * (1 - noise) + rng.uniform(-1, 1, len(x)) * noise
    return s * env(len(x), 0.001, 90)


def place(buf, sig, at):
    i = int(at * SR)
    buf[i:i + len(sig)] += sig[: max(0, len(buf) - i)]


def norm(x, peak=0.8):
    return x / max(1e-9, np.abs(x).max()) * peak


def save(name, x):
    x = norm(x)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        with wave.open(f.name, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f.name, "-codec:a", "libmp3lame", "-q:a", "5", str(OUT / f"sfx.{name}.mp3")], check=True)
    print(name, f"{len(x) / SR:.2f}s")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # tick: короткий сухой щелчок раз в секунду
    save("tick", click(0.05, 1500, 0.35))
    # timer10: двойной сигнал «пора»
    b = np.zeros(int(SR * 0.45))
    place(b, bell(880, 0.18, 14), 0); place(b, bell(880, 0.18, 14), 0.2)
    save("timer10", b)
    # ok: восходящее арпеджио До-Ми-Соль-До
    b = np.zeros(int(SR * 1.3))
    for i, f in enumerate([523.25, 659.25, 783.99, 1046.5]):
        place(b, bell(f, 0.9, 4.5) * (1 if i < 3 else 1.3), i * 0.11)
    save("ok", b)
    # fail: два низких нисходящих тона
    b = np.zeros(int(SR * 0.9))
    for i, f in enumerate([220.0, 164.8]):
        x = t(0.45)
        s = (np.sign(np.sin(2 * np.pi * f * x)) * 0.25 + np.sin(2 * np.pi * f * x)) * env(len(x), 0.01, 5)
        place(b, s, i * 0.28)
    save("fail", b)
    # spin: трещотка волчка — щелчки с замедлением (интервал растёт ~ как при торможении)
    d = 5.2
    b = np.zeros(int(SR * (d + 0.3)))
    at, gap = 0.0, 0.035
    while at < d:
        place(b, click(0.035, 1100 + rng.uniform(-80, 80), 0.55) * (0.5 + 0.5 * (1 - at / d) + 0.2), at)
        gap *= 1.045
        at += gap
    save("spin", b)


if __name__ == "__main__":
    main()
