"""Показывает, что реально сейчас на экране AWTRIX из дотных приложений."""
import time

import requests

B = "http://192.168.31.41/api/v1"


def current():
    return requests.get(f"{B}/device", timeout=5).json().get("currentApp")


apps = requests.get(f"{B}/apps", timeout=5).json()
dota = [a["name"] for a in apps if a["name"].startswith("dota_")]
print("дотные приложения:", dota)

for name in dota:
    requests.put(f"{B}/apps/active", json={"name": name, "fast": True}, timeout=5)
    time.sleep(1.0)
    # ждём, пока AWTRIX реально переключится на нужное приложение
    for _ in range(20):
        if current() == name:
            break
        time.sleep(0.25)
    on = current()
    s = requests.get(f"{B}/display/screen", timeout=5).json()
    px, w, h = s["pixels"], s["width"], s["height"]

    print(f"\n== запрошен {name} / на экране {on}")
    for y in range(h):
        row = ""
        for x in range(w):
            v = px[y * w + x]
            if v == 0:
                row += "."
            elif v == 0x40FF40:
                row += "#"
            elif v == 0xFF4040:
                row += "R"
            elif v == 0x101010:
                row += "-"
            else:
                row += "*"
        print(row)