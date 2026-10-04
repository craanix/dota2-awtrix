"""
Dota 2 → AWTRIX-NG bridge

Слушает GSI (Game State Integration) от Dota 2 на порту 42069 и мониторит
console.log на предмет найденного матча.

Нотификация: "Принять" (белым по зелёному, 15 сек) когда матч найден.
Экраны в ротации AWTRIX во время игры:
  dota_stat  — KDA цветными фрагментами + герой
  dota_farm  — LH / denies / GPM / XPM
  dota_base  — полосы HP базы radiant/dire
  dota_dead  — таймер до респау (вместо dota_stat, пока мёртв)

AWTRIX-NG API v1:
  POST   /api/v1/notifications       — одноразовая нотификация
  PUT    /api/v1/apps/pushed/{name}  — приложение в ротации
  DELETE /api/v1/apps/{name}         — удалить приложение
"""

import json
import os
import re
import threading
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

# ── Настройки ──────────────────────────────────────────────────────
AWTRIX_IP = "192.168.31.41"
AWTRIX_BASE = f"http://{AWTRIX_IP}/api/v1"

DOTA_GSI_PORT = 42069

# Путь к console.log Dota 2 (нужен -console -condebug в параметрах запуска)
DOTA_LOG_PATH = r"F:\SteamLibrary\steamapps\common\dota 2 beta\game\dota\console.log"

# Сигнал "матч найден, надо принять"
MATCH_ACCEPT_PATTERNS = [
    re.compile(r"k_EMsgGCReadyUpStatus"),
]

# Если рядом есть эти маркеры — это practice/кастом, а не матчмейкинг.
# ReadyUpStatus шлётся в любом лобби, без этой проверки ловим false positive.
IGNORE_IF_RECENT = [
    re.compile(r"PracticeLobby"),
    re.compile(r"CustomGame"),
    re.compile(r"Practice"),
]

NOTIFY_COOLDOWN = 30  # минимум сек между нотификациями
DEBUG_CONSOLE = False  # True = писать все строки из console.log (для отладки)
RECENT_WINDOW = 120  # сколько последних строк смотреть при поиске маркеров

# Как долго висит каждый экран (мс)
APP_DURATION_MS = 5000
# Как часто обновлять экраны (сек)
APP_PUSH_INTERVAL = 1.0

LOG_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.log")
# Сохранённая ротация пользователя — на диск, чтобы переживать перезапуск скрипта
ROTATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rotation.json")

# Если во время игры GSI молчит дольше этого, считаем матч законченным
GSI_STALE_SEC = 20

# Состояния, в которых игра идёт
PLAYING_STATES = (
    "DOTA_GAMERULES_STATE_HERO_SELECTION",
    "DOTA_GAMERULES_STATE_STRATEGY_TIME",
    "DOTA_GAMERULES_STATE_PRE_GAME",
    "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
)

# Цвета
C_KILL = "#FFFFFF"
C_DEATH = "#FF4040"
C_ASSIST = "#40FF80"
C_ACCENT = "#FFC040"
C_RADIANT = "#40FF40"
C_DIRE = "#FF4040"


# ── Состояние ──────────────────────────────────────────────────────
class GameState:
    in_game = False
    hero = ""
    kills = 0
    deaths = 0
    assists = 0
    last_hits = 0
    denies = 0
    gpm = 0
    xpm = 0
    level = 0
    health = 0
    max_health = 0
    respawn_seconds = 0
    alive = True
    team_name = ""
    gold = 0
    game_time = 0
    radiant_score = 0
    dire_score = 0
    building = {}
    last_notify_ts = 0.0
    dead_app_live = False
    checked_fields = False
    last_gsi_ts = 0.0


state = GameState()
_log_lock = threading.Lock()


def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with _log_lock:
        try:
            with open(LOG_OUT, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
    print(line, flush=True)


# ── AWTRIX helpers ─────────────────────────────────────────────────
def awtrix_notify(text: str, background: str = "", text_color: str = "",
                  duration_ms: int = 5000, stack: bool = True,
                  text_case: str = "", sound: str = ""):
    payload = {"text": text, "durationMs": duration_ms}
    if background:
        payload["backgroundColor"] = background
    if text_color:
        payload["textColor"] = text_color
    if text_case:
        payload["textCase"] = text_case
    if not stack:
        payload["stack"] = False
    if sound:
        payload["sound"] = sound
    try:
        r = requests.post(f"{AWTRIX_BASE}/notifications", json=payload, timeout=3)
        log(f"notify '{text}' → {r.status_code} {r.text[:80]}")
    except Exception as e:
        log(f"notify error: {e}")


def awtrix_app(name: str, payload: dict):
    payload = dict(payload)
    payload.setdefault("durationMs", APP_DURATION_MS)
    try:
        r = requests.put(f"{AWTRIX_BASE}/apps/pushed/{name}", json=payload, timeout=3)
        if r.status_code != 200:
            log(f"app/{name} → {r.status_code} {r.text[:120]}")
    except Exception as e:
        log(f"app/{name} error: {e}")


def awtrix_delete_app(name: str):
    try:
        requests.delete(f"{AWTRIX_BASE}/apps/{name}", timeout=3)
    except Exception:
        pass


def fmt_networth(n) -> str:
    try:
        n = int(n)
    except Exception:
        return "-"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# ── Управление ротацией ────────────────────────────────────────────
# Имена наших приложений — они остаются в ротации во время игры
DOTA_APPS = ("dota_stat", "dota_farm", "dota_base", "dota_dead")
# Порядок экранов во время игры (без dota_dead — он создаётся только при смерти)
DOTA_ORDER = ("dota_stat", "dota_farm", "dota_base")

_saved_rotation = None


def list_apps() -> list:
    try:
        r = requests.get(f"{AWTRIX_BASE}/apps", timeout=4)
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        log(f"apps list error: {e}")
        return []


def set_rotation(order=None, disabled=None):
    body = {}
    if order is not None:
        body["order"] = order
    body["disabled"] = disabled or []  # disabled всегда обязателен
    try:
        r = requests.put(f"{AWTRIX_BASE}/apps/order", json=body, timeout=4)
        log(f"rotation set order={order} disabled={len(disabled or [])} → {r.status_code}")
    except Exception as e:
        log(f"rotation error: {e}")


def save_rotation():
    """Запоминаем ротацию пользователя, чтобы вернуть как было.

    Сохраняем на диск: если скрипт перезапустится посреди игры, исходное
    состояние не потеряется. Если мы УЖЕ в игровой ротации — не перезаписываем,
    иначе сохраним собственную же игровую ротацию и потом восстановим её.
    """
    global _saved_rotation

    if _saved_rotation:
        return  # уже сохранено

    apps = list_apps()
    order = [a["name"] for a in apps if a.get("present") and a.get("inLoop")]
    disabled = [a["name"] for a in apps if not a.get("enabled")]

    # если в ротации только наши экраны — это не исходное состояние
    if order and all(n.startswith("dota_") for n in order):
        log("rotation: already in dota mode, not overwriting saved state")
        return

    _saved_rotation = {"order": order, "disabled": disabled}
    try:
        with open(ROTATION_FILE, "w", encoding="utf-8") as fh:
            json.dump(_saved_rotation, fh)
    except Exception as e:
        log(f"rotation save error: {e}")
    log(f"rotation saved: order={order} disabled={disabled}")


def load_saved_rotation():
    global _saved_rotation
    if _saved_rotation:
        return _saved_rotation
    try:
        with open(ROTATION_FILE, encoding="utf-8") as fh:
            _saved_rotation = json.load(fh)
            log(f"rotation loaded from disk: {_saved_rotation}")
    except Exception:
        _saved_rotation = None
    return _saved_rotation


def clear_saved_rotation():
    global _saved_rotation
    _saved_rotation = None
    try:
        os.remove(ROTATION_FILE)
    except OSError:
        pass


def enter_dota_rotation():
    """Во время игры в ротации только наши экраны."""
    apps = list_apps()
    names = [a["name"] for a in apps]
    disabled = [n for n in names if not n.startswith("dota_")]
    set_rotation(order=list(DOTA_ORDER), disabled=disabled)


def restore_rotation():
    """Обычная ротация + обычные часы.

    Восстанавливаем ровно то, что было до игры: сохранённый порядок И сохранённый
    список disabled. Раньше здесь стоял пустой список — из-за этого включались
    приложения, которые пользователь выключил сам.
    """
    apps = list_apps()
    names = [a["name"] for a in apps]

    saved = load_saved_rotation() or {}
    order = [n for n in (saved.get("order") or [])
             if not n.startswith("dota_")]
    disabled = [n for n in (saved.get("disabled") or [])
                if n in names and not n.startswith("dota_")]

    if not order:
        # сохранения нет — собираем из текущего состояния, но выключенное не трогаем
        order = [a["name"] for a in apps
                 if a.get("present") and a.get("inLoop")
                 and not a["name"].startswith("dota_")]

    # обычные часы гарантированно в ротации
    if "Time" in names and "Time" not in order:
        order.insert(0, "Time")

    set_rotation(order=order, disabled=disabled)
    clear_saved_rotation()


# ── Экраны ─────────────────────────────────────────────────────────
def screen_stat() -> dict:
    """KDA + герой. 8 символов в мелком шрифте."""
    frags = [
        {"text": str(state.kills), "color": C_KILL},
        {"text": "/", "color": C_ACCENT},
        {"text": str(state.deaths), "color": C_DEATH},
        {"text": "/", "color": C_ACCENT},
        {"text": str(state.assists), "color": C_ASSIST},
    ]
    return {"text": frags, "textCenter": True}


def screen_farm() -> dict:
    """LH / DN / GPM — до 8 символов."""
    parts = [
        {"text": str(state.last_hits), "color": C_KILL},
        {"text": "/", "color": C_ACCENT},
        {"text": str(state.denies), "color": C_ASSIST},
        {"text": " ", "color": C_ACCENT},
        {"text": str(state.gpm), "color": C_ACCENT},
    ]
    return {"text": parts, "textCenter": True}


def screen_dead() -> dict:
    """Таймер до респау — крупно."""
    secs = max(0, int(state.respawn_seconds))
    return {"text": str(secs), "font": "large", "textColor": C_DEATH,
            "textCenter": True}


def team_base_pct(team: str) -> int:
    """Средний процент HP построек команды (0-100)."""
    b = state.building or {}
    vals = []

    def team_of(obj) -> str:
        t = obj.get("team")
        if t is None:
            return ""
        s = str(t).lower()
        if s in ("radiant", "2"):
            return "radiant"
        if s in ("dire", "3"):
            return "dire"
        return ""

    an = b.get("ancient") or {}
    if isinstance(an, dict) and an.get("max_health"):
        vals.append(an["health"] / an["max_health"])

    for group in ("towers", "barracks"):
        for obj in (b.get(group) or {}).values():
            if not isinstance(obj, dict):
                continue
            if team_of(obj) != team:
                continue
            mh = obj.get("max_health")
            if mh:
                vals.append(obj.get("health", 0) / mh)

    if not vals:
        return 0
    return int(max(0.0, min(1.0, sum(vals) / len(vals))) * 100)


def screen_base() -> dict:
    """Полосы: radiant сверху, dire снизу.

    Числа под полосками снимают неоднозначность:
      "54% 26%"  — проценты HP построек (работает блок building)
      "53:23"    — просто счёт убийств (fallback, building ещё не подключён)
    """
    r = team_base_pct("radiant")
    d = team_base_pct("dire")

    if r == 0 and d == 0:
        total = state.radiant_score + state.dire_score
        w_r = w_d = 0
        if total:
            w_r = round(32 * state.radiant_score / total)
            w_d = round(32 * state.dire_score / total)
        label = f"{state.radiant_score}:{state.dire_score}"
    else:
        w_r = round(32 * r / 100)
        w_d = round(32 * d / 100)
        label = f"{r}% {d}%"

    draw = [
        # полоски в 1 пиксель сверху и снизу, текст занимает середину
        ["rectFill", 0, 0, 32, 1, "#101010"],
        ["rectFill", 0, 7, 32, 1, "#101010"],
    ]
    if w_r > 0:
        draw.append(["rectFill", 0, 0, min(32, w_r), 1, C_RADIANT])
    if w_d > 0:
        draw.append(["rectFill", 0, 7, min(32, w_d), 1, C_DIRE])

    return {"draw": draw, "text": label, "textCenter": True,
            "textInFront": True}


def end_game():
    """Матч закончился: убираем экраны и возвращаем обычную ротацию."""
    for n in DOTA_APPS:
        awtrix_delete_app(n)
    state.dead_app_live = False
    state.in_game = False
    state.checked_fields = False
    restore_rotation()
    awtrix_notify(
        f"GG {state.kills}/{state.deaths}/{state.assists}",
        background="#331A00", text_color=C_ACCENT, duration_ms=8000)
    log("game over, rotation restored")


# ── GSI HTTP Server ────────────────────────────────────────────────
class GSIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return
        try:
            self._process(data)
        except Exception as e:
            log(f"gsi process error: {e}")

    def _process(self, data: dict):
        map_info = data.get("map") or {}
        player = data.get("player") or {}
        hero = data.get("hero") or {}

        state.last_gsi_ts = time.time()
        game_state = map_info.get("game_state", "")

        if game_state not in PLAYING_STATES:
            if state.in_game:
                end_game()
            state.in_game = False
            state.building = {}
            return

        if not state.in_game:
            log(f"game start: {game_state}")
            # снимаем реальную структуру GSI, чтобы проверять имена полей, а не гадать
            try:
                sample = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "gsi_sample.json")
                with open(sample, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=1, ensure_ascii=False)
                log(f"gsi sample saved: top-level keys = {list(data.keys())}")
            except Exception as e:
                log(f"gsi sample error: {e}")
            save_rotation()
            enter_dota_rotation()
            awtrix_notify("GO", background="#003300",
                          text_color="#00FF00", duration_ms=2500)

        state.in_game = True
        state.kills = player.get("kills", 0)
        state.deaths = player.get("deaths", 0)
        state.assists = player.get("assists", 0)
        state.last_hits = player.get("last_hits", 0)
        state.denies = player.get("denies", 0)
        state.gpm = player.get("gpm", 0)
        state.xpm = player.get("xpm", 0)
        state.gold = player.get("gold", 0)
        state.team_name = player.get("team_name", "")

        state.game_time = map_info.get("game_time", 0)
        state.radiant_score = map_info.get("radiant_score", 0)
        state.dire_score = map_info.get("dire_score", 0)

        # respawn_seconds/health живут в блоке hero, а не player
        state.level = hero.get("level", 0)
        state.health = hero.get("health", 0)
        state.max_health = hero.get("max_health", 0)
        state.respawn_seconds = hero.get("respawn_seconds", 0)
        state.alive = bool(hero.get("alive", False))

        name = hero.get("name") or ""
        if name:
            state.hero = name.replace("npc_dota_hero_", "").replace("_", " ").title()

        state.building = data.get("building") or {}

        # Разовая проверка: какие из нужных полей реально пришли
        if not state.checked_fields:
            state.checked_fields = True
            log(f"gsi fields: player.gpm={'gpm' in player}, player.xpm={'xpm' in player}, "
                f"hero.respawn_seconds={'respawn_seconds' in hero}, "
                f"building={'yes' if state.building else 'NO (нужен перезапуск Dota)'}")

    def log_message(self, fmt, *args):
        pass


# ── Пул экранов ────────────────────────────────────────────────────
def push_screens():
    if not state.in_game:
        return

    dead = state.respawn_seconds and state.respawn_seconds > 0

    if dead:
        if not state.dead_app_live:
            awtrix_delete_app("dota_stat")
            state.dead_app_live = True
        awtrix_app("dota_dead", screen_dead())
    else:
        if state.dead_app_live:
            awtrix_delete_app("dota_dead")
            state.dead_app_live = False
        awtrix_app("dota_stat", screen_stat())

    awtrix_app("dota_farm", screen_farm())
    awtrix_app("dota_base", screen_base())


def screens_loop():
    while True:
        # Страховка: если во время игры GSI замолчал — матч наверняка кончился.
        # Dota не обязана слать данные после возврата в главное меню.
        if state.in_game and state.last_gsi_ts:
            if time.time() - state.last_gsi_ts > GSI_STALE_SEC:
                log("gsi stale, forcing game over")
                end_game()
        push_screens()
        time.sleep(APP_PUSH_INTERVAL)


# ── Console.log monitor ────────────────────────────────────────────
def monitor_console():
    fh = open(LOG_OUT, "a", encoding="utf-8", buffering=1)
    recent = deque(maxlen=RECENT_WINDOW)
    f = None
    ino = None

    def wlog(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        fh.write(line + "\n")

    wlog(f"monitor start, log={DOTA_LOG_PATH}")

    while True:
        if f is None:
            try:
                st = os.stat(DOTA_LOG_PATH)
                f = open(DOTA_LOG_PATH, "rb")
                ino = st.st_ino
                f.seek(0, 2)
                wlog(f"opened console.log size={st.st_size}")
            except FileNotFoundError:
                time.sleep(2)
                continue
            except Exception as e:
                wlog(f"open error: {e}")
                time.sleep(2)
                continue

        chunk = f.readline()
        if not chunk:
            try:
                st = os.stat(DOTA_LOG_PATH)
                if st.st_ino != ino or st.st_size < f.tell():
                    wlog("file recreated/truncated -> reopen")
                    f.close()
                    f = None
                    continue
            except FileNotFoundError:
                pass
            except Exception as e:
                wlog(f"stat error: {e}")
            time.sleep(0.4)
            continue

        line = chunk.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        if DEBUG_CONSOLE:
            wlog(f"[RAW] {line}")

        recent.append(line)

        if not any(p.search(line) for p in MATCH_ACCEPT_PATTERNS):
            continue

        ctx = "\n".join(recent)
        if any(p.search(ctx) for p in IGNORE_IF_RECENT):
            wlog(f"ignored (practice/custom): {line}")
            continue

        now = time.time()
        if now - state.last_notify_ts > NOTIFY_COOLDOWN:
            wlog(f"*** MATCH DETECTED: {line}")
            awtrix_notify(
                "Принять",
                background="#004400",
                text_color="#FFFFFF",
                duration_ms=15000,
                stack=False,
                text_case="asTyped",
            )
            state.last_notify_ts = now
        else:
            wlog(f"match (cooldown): {line}")


# ── Main ───────────────────────────────────────────────────────────
def main():
    log("=" * 50)
    log("  Dota 2 -> AWTRIX-NG Bridge")
    log(f"  AWTRIX: {AWTRIX_IP}")
    log(f"  GSI port: {DOTA_GSI_PORT}")
    log("=" * 50)

    threading.Thread(target=monitor_console, daemon=True).start()
    threading.Thread(target=screens_loop, daemon=True).start()

    server = HTTPServer(("0.0.0.0", DOTA_GSI_PORT), GSIHandler)
    log(f"[GSI] Listening on 0.0.0.0:{DOTA_GSI_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")
        for n in ("dota_stat", "dota_farm", "dota_base", "dota_dead"):
            awtrix_delete_app(n)
        server.shutdown()


if __name__ == "__main__":
    main()