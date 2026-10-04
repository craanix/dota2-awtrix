# Dota 2 → AWTRIX-NG

Bridge between Dota 2 and an AWTRIX-NG LED matrix. Shows a "Принять" (Accept)
notification when a match is found, then puts KDA, farm and base status on the
panel during the game.

[Русский](README.md)

## What it does

**Outside a game** — your normal app rotation (clock, ISS, Klipper, weather).

**Match notification.** As soon as Dota finds a match, the matrix gets
"Принять" — white on green, for 15 seconds. Miss the accept window and it
clears itself.

**During a game** the rotation switches to the Dota screens, everything else is
switched off and comes back after the match:

| Screen | Shows |
|---|---|
| `dota_stat` | `K/D/A` — kills, deaths, assists in different colors |
| `dota_farm` | `LH/DN` and GPM — last hits, denies, gold per minute |
| `dota_base` | radiant on top, dire at the bottom. With building GSI data — `54% 26%`, without it — kill score `53:23` |
| `dota_dead` | Big respawn countdown. Replaces `dota_stat` while you are dead |

On match end you get `GG K/D/A`.

## Requirements

- AWTRIX-NG, firmware ≥ 1.0, HTTP API v1
- Dota 2
- Python 3.8+ and `requests`
- Windows (paths and autostart are written for Windows)

## Setup

### 1. GSI config

Create:

```
<Steam>\steamapps\common\dota 2 beta\game\dota\cfg\gamestate_integration\gamestate_integration_awtrix.cfg
```

Contents:

```cfg
"AWTRIX Dota2 Integration"
{
	"uri"        "http://localhost:42069"
	"timeout" 	"5.0"
	"buffer"  	"0.1"
	"throttle" 	"0.1"
	"heartbeat" 	"30.0"
	"data"
	{
		"provider"     "1"
		"map"          "1"
		"player"       "1"
		"hero"         "1"
		"abilities"    "1"
		"items"        "1"
		"draft"        "1"
		"wearables"    "1"
		"building"     "1"
	}
}
```

> **Important.** GSI reads this file **at client startup**. If you add a block
> later, restart Dota or it will not take effect. After startup check
> `bridge.log` for `building=yes`. `building=NO` means you still need a restart.

### 2. Enable Dota's console log

Match detection goes through `console.log`, so the log must be on:

Steam → right-click Dota 2 → Properties → Launch Options:

```
-console -condebug
```

Fully close Dota before starting it again, otherwise the option is not applied.

If you have a firewall prompt, allow port `42069`.

### 3. Run

```bash
pip install -r requirements.txt
python dota_awtrix.py
```

The script runs in the background and writes to `bridge.log`.

### 4. Autostart

Drop a `dota2-awtrix.bat` into the Windows Startup folder (`shell:startup`):

```bat
@echo off
cd /d C:\path\to\project
start /min pythonw dota_awtrix.py
```

## Why console.log is needed

Game State Integration **cannot see the lobby**. The full `DOTA_GameState` enum
from `dota_shared_enums.proto` is `INIT`, `WAIT_FOR_PLAYERS_TO_LOAD`,
`HERO_SELECTION`, `STRATEGY_TIME`, `PRE_GAME`, `GAME_IN_PROGRESS`, `POST_GAME`,
`DISCONNECT`, `TEAM_SHOWCASE`, `CUSTOM_GAME_SETUP`, `WAIT_FOR_MAP_TO_LOAD`,
`SCENARIO_SETUP`, `PLAYER_DRAFT` — all of which exist only **after** connecting to
a game server. There is no "match found, awaiting accept" state, and no lobby
block in the GSI schema at all.

So the "press Accept" moment is picked up from a `console.log` line:

```
[GCClient] Recv msg 7170 (k_EMsgGCReadyUpStatus), 21 bytes
```

It arrives when the match lobby is created and the player is expected to answer.

### False positives

`k_EMsgGCReadyUpStatus` arrives in **any** lobby, including practice and custom
games. The script therefore inspects a sliding window of the last 120 log lines:
if `PracticeLobby`, `CustomGame` or `Practice` appears nearby, the trigger is
ignored.

That also means the limitation: if you are in a party lobby and someone readies
up, you will get a notification. There is no way to tell that apart from real
matchmaking by log content.

## Configuration

At the top of `dota_awtrix.py`:

| Variable | Default | Meaning |
|---|---|---|
| `AWTRIX_IP` | `192.168.31.41` | matrix address |
| `DOTA_GSI_PORT` | `42069` | port the script listens on |
| `DOTA_LOG_PATH` | `<F:>\...\game\dota\console.log` | path to Dota's log |
| `NOTIFY_COOLDOWN` | `30` | seconds between match notifications |
| `APP_DURATION_MS` | `5000` | how long each screen stays |
| `DEBUG_CONSOLE` | `False` | `True` — mirror all of Dota's log into `bridge.log` |
| `GSI_STALE_SEC` | `20` | if GSI goes quiet longer than this, treat the match as over |

## Debugging

```bash
# what the matrix is showing right now
python list_apps.py

# what has been happening
Get-Content bridge.log -Tail 40
```

`bridge.log` records everything: rotation switches, detected matches, rejected
false positives. Lines worth looking for:

- `*** MATCH DETECTED` — detector fired
- `ignored (practice/custom)` — lobby filtered out
- `rotation saved` / `rotation restored` — rotation switching
- `gsi fields:` — which fields Dota actually sends

On startup the script saves `gsi_sample.json` once — the raw GSI payload. If
something shows zeros, look there first.

## Limitations

- Accept detection requires `-console -condebug`
- Dota deletes `console.log` on exit — normal, the script reopens the file
- The `building` block needs a Dota restart after editing the config
- The rotation is restored from the saved list: if you rearrange apps by hand
  during a game, you get back whatever was there before
- Port `42069` already in use — the script will not start and GSI will silently
  do nothing

## AWTRIX-NG API

Four routes are used:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/notifications` | "Принять", "GO", "GG" |
| `PUT` | `/api/v1/apps/pushed/{name}` | KDA / farm / base / death screens |
| `PUT` | `/api/v1/apps/order` | rotation switching |
| `DELETE` | `/api/v1/apps/{name}` | drop a screen |

## License

MIT