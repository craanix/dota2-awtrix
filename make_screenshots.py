"""Генерирует PNG-скриншоты экранов для README.

Шрифт и раскладку считает сама матрица: скрипт отправляет payload, читает
кадровый буфер через GET /api/v1/display/screen и рисует его как есть.
Ничего не реконструируется на стороне Python — пиксели настоящие.

    python make_screenshots.py [адрес_матрицы]

Нужен Pillow: pip install Pillow
"""
import os
import sys
import time

import requests
from PIL import Image, ImageDraw

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.31.41"
BASE = f"http://{HOST}/api/v1"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "screens")

SCALE = 14          # размер одного светодиода в пикселях картинки
GAP = 2             # зазор между светодиодами
RADIUS = 3          # скругление
BG = (10, 10, 10)

# ── payloads ───────────────────────────────────────────────────────
C_KILL = "#FFFFFF"
C_DEATH = "#FF4040"
C_ASSIST = "#40FF80"
C_ACCENT = "#FFC040"
C_RADIANT = "#40FF40"
C_DIRE = "#FF4040"


def frag(text, color):
    return {"text": text, "color": color}


def two_bars(w_r, w_d, label):
    draw = [
        ["rectFill", 0, 0, 32, 1, "#101010"],
        ["rectFill", 0, 7, 32, 1, "#101010"],
    ]
    if w_r > 0:
        draw.append(["rectFill", 0, 0, min(32, w_r), 1, C_RADIANT])
    if w_d > 0:
        draw.append(["rectFill", 0, 7, min(32, w_d), 1, C_DIRE])
    return {"draw": draw, "text": label, "textCenter": True, "textInFront": True}


def payloads():
    """Подборки правдоподобных данных для каждого экрана."""
    return {
        "dota_stat": {
            "text": [frag("12", C_KILL), frag("/", C_ACCENT), frag("3", C_DEATH),
                     frag("/", C_ACCENT), frag("8", C_ASSIST)],
            "textCenter": True,
        },
        "dota_farm": {
            "text": [frag("143", C_KILL), frag("/", C_ACCENT), frag("7", C_ASSIST),
                     frag(" ", C_ACCENT), frag("612", C_ACCENT)],
            "textCenter": True,
        },
        "dota_base": two_bars(22, 10, "53:23"),
        "dota_dead": {"text": "23", "font": "large", "textColor": C_DEATH,
                      "textCenter": True},
    }


NOTIFY = {
    "text": "Принять",
    "backgroundColor": "#004400",
    "textColor": "#FFFFFF",
    "durationMs": 30000,
    "hold": True,
    "stack": False,
    "textCase": "asTyped",
}


# ── работа с матрицей ──────────────────────────────────────────────
def read_screen():
    r = requests.get(f"{BASE}/display/screen", timeout=5)
    r.raise_for_status()
    d = r.json()
    return d["width"], d["height"], d["pixels"]


def current_app():
    try:
        return requests.get(f"{BASE}/device", timeout=5).json().get("currentApp")
    except Exception:
        return None


def wait_for_app(name, timeout=8.0):
    """Ждём, пока матрица реально переключится на нужное приложение."""
    end = time.time() + timeout
    while time.time() < end:
        if current_app() == name:
            time.sleep(0.6)  # даём кадру дорисоваться
            return True
        time.sleep(0.2)
    return False


def capture(name, png):
    w, h, px = read_screen()
    img = Image.new("RGB", (w * (SCALE + GAP) + GAP, h * (SCALE + GAP) + GAP), BG)
    d = ImageDraw.Draw(img)
    for y in range(h):
        for x in range(w):
            v = px[y * w + x]
            if not v:
                continue
            r, g, b = (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
            # приглушаем, чтобы не выглядело как засветка
            r, g, b = (int(c * 0.82) for c in (r, g, b))
            x0 = GAP + x * (SCALE + GAP)
            y0 = GAP + y * (SCALE + GAP)
            d.rounded_rectangle([x0, y0, x0 + SCALE - 1, y0 + SCALE - 1],
                                radius=RADIUS, fill=(r, g, b))
    path = os.path.join(OUT, png)
    img.save(path)
    lit = sum(1 for v in px if v)
    print(f"  {name:>12} -> {png}  ({lit} lit px)")
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"AWTRIX: {HOST}")

    print("apps:")
    for name, payload in payloads().items():
        r = requests.put(f"{BASE}/apps/pushed/{name}", json=payload, timeout=5)
        print(f"  push {name}: {r.status_code}")

    print("capture:")
    for name, png in (
        ("dota_stat", "kda.png"),
        ("dota_farm", "farm.png"),
        ("dota_base", "base.png"),
        ("dota_dead", "death-timer.png"),
    ):
        requests.put(f"{BASE}/apps/active", json={"name": name, "fast": True}, timeout=5)
        if wait_for_app(name):
            capture(name, png)
        else:
            print(f"  {name}: не дождались, пропускаем")

    print("notification:")
    requests.post(f"{BASE}/notifications", json=NOTIFY, timeout=5)
    time.sleep(1.5)
    capture("Принять", "accept.png")
    requests.delete(f"{BASE}/notifications/active", timeout=5)

    print("cleanup:")
    for name in payloads():
        requests.delete(f"{BASE}/apps/{name}", timeout=4)
        print(f"  {name}: удалён")

    print(f"\nготово: {OUT}")


if __name__ == "__main__":
    main()