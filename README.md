# Dota 2 → AWTRIX-NG

Мост между Dota 2 и LED-матрицей [AWTRIX-NG](https://blueforcer.github.io/awtrix-ng/).
Показывает нотификацию «Принять», когда найден матч, и во время игры выводит
KDA, фарм и состояние базы.

[English](README_EN.md)

## Возможности

**Вне игры** — обычная ротация приложений матрицы.

**Уведомление о матче.** Когда Dota находит матч, на панель приходит «Принять» —
белым по зелёному, на 15 секунд. Не успел принять — надпись исчезнет сама.

**Во время игры** ротация переключается на экраны Dota, остальные приложения
выключаются и возвращаются после матча:

| Экран | Содержимое |
|---|---|
| `dota_stat` | `K/D/A` — убийства, смерти, помощь разными цветами |
| `dota_farm` | `LH/DN` и GPM — добито крипов, отжато, золото в минуту |
| `dota_base` | radiant сверху, dire снизу. `54% 26%` — если GSI отдаёт HP построек, `53:23` — счёт |
| `dota_dead` | Крупно тает секунды до респау. Заменяет `dota_stat`, пока игрок мёртв |

По окончании матча прилетает `GG K/D/A`.

## Как это выглядит

| Уведомление о матче | KDA | Фарм |
|---|---|---|
| ![Принять](docs/screens/accept.png) | ![KDA](docs/screens/kda.png) | ![Фарм](docs/screens/farm.png) |

| База | Таймер смерти |
|---|---|
| ![База](docs/screens/base.png) | ![Таймер смерти](docs/screens/death-timer.png) |

Полоски на экране базы — radiant сверху, dire снизу. Под ними либо проценты HP
построек (`54% 26%`), либо счёт (`53:23`), если блок `building` от GSI ещё не
пришёл — это видно по формату чисел.

Отрисовку делает сама матрица: скрипты из `make_screenshots.py` отправляют
payload, читают кадровый буфер и собирают из него PNG, так что на картинках
настоящие пиксели, а не реконструкция шрифта.

> Надпись «Принять» на панели выглядит капителью, хотя передаётся с правильным
> регистром: во встроенном шрифте AWTRIX нет строчных глифов, он подставляет
> прописные. Это ограничение шрифта, а не настройки.

## Требования

- Матрица AWTRIX-NG с прошивкой ≥ 1.0 и включённым HTTP API v1 —
  см. [HTTP API v1](https://blueforcer.github.io/awtrix-ng/reference/http/)
- Dota 2
- Python 3.8+ и [`requests`](https://pypi.org/project/requests/)
- Путь к игре находится автоматически в библиотеках Steam. Проверено на Windows;
  на Linux/macOS работает поиск через `libraryfolders.vdf`, но автозагрузка в
  примерах ниже — Windows

## Установка

### 1. Настройки

`config.json` лежит в репозитории и содержит значения по умолчанию:

```json
{
  "awtrix_ip": null,
  "gsi_port": 42069,
  "dota_dir": null
}
```

- `awtrix_ip` — адрес матрицы. Узнать можно в веб-интерфейсе AWTRIX; там же видно
  mDNS-имя вида `awtrixng-XXXXXX.local`, если есть желание использовать его вместо IP
- `dota_dir` — папка `...\dota 2 beta\game\dota`, если автопоиск не сработал
- `gsi_port` — порт, который слушает скрипт

Те же значения можно задать переменными окружения `AWTRIX_IP`, `DOTA_DIR`,
`DOTA_GSI_PORT` — они имеют приоритет над файлом.

### 2. Конфиг GSI

Создай файл `gamestate_integration_awtrix.cfg` в
`<библиотека Steam>\steamapps\common\dota 2 beta\game\dota\cfg\gamestate_integration\`
(для Dota 2 он обычно уже существует, рядом лежит конфиг Overwolf):

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

Механика GSI описана в
[Game State Integration](https://developer.valvesoftware.com/wiki/Game_State_Integration)
у Valve, схема полей Dota — в
[ValvePython/dota2-gsi](https://github.com/ValvePython/dota2-gsi).

> **Важно.** GSI читает этот файл **при запуске клиента**. Добавишь блок позже —
> перезапусти Dota, иначе он не заработает. Проверить можно в `bridge.log`:
> должно быть `building=yes` вместо `building=NO`.

### 3. Логирование консоли Dota

Детект «матч найден» идёт через `console.log`, поэтому лог нужно включить.
В Steam: ПКМ по Dota 2 → Свойства → Параметры запуска:

```
-console -condebug
```

Закрой Dota полностью перед следующим запуском, иначе параметр не применится.
Без него файла `console.log` просто не существует.

Если появится запрос брандмауэра — разреши порт `gsi_port`.

### 4. Запуск

```bash
pip install -r requirements.txt
python dota_awtrix.py
```

Скрипт работает в фоне, всё пишет в `bridge.log`.

### 5. Автозапуск (Windows)

Файл `dota2-awtrix.bat` в папке автозагрузки (`Win+R` → `shell:startup`):

```bat
@echo off
cd /d C:\путь\к\проекту
start /min pythonw dota_awtrix.py
```

Строка `set AWTRIX_IP=...` нужна, только если адрес не задан в `config.json`.
Запуск в автозагрузке не должен поднимать второй экземпляр — скрипт сам
откажется занять порт, если он уже слушается, но лучше не создавать ситуацию.

## Почему нужен console.log

Game State Integration **не видит лобби**. Полный перечень
[`DOTA_GameState`](https://github.com/SteamDatabase/GameTracking-Dota2/blob/master/Protobufs/dota_shared_enums.proto):
`INIT`, `WAIT_FOR_PLAYERS_TO_LOAD`, `HERO_SELECTION`, `STRATEGY_TIME`,
`PRE_GAME`, `GAME_IN_PROGRESS`, `POST_GAME`, `DISCONNECT`, `TEAM_SHOWCASE`,
`CUSTOM_GAME_SETUP`, `WAIT_FOR_MAP_TO_LOAD`, `SCENARIO_SETUP`, `PLAYER_DRAFT`.
Все они существуют только **после** подключения к игровому серверу. Состояния
«матч найден, ждём принятия» среди них нет, и блока лобби в схеме GSI тоже нет —
в документации перечислены только `provider`, `map`, `player`, `hero`,
`abilities`, `items`, `draft`, `wearables`, `building` и несколько других.

Поэтому момент «нажми Принять» ловится по строке в `console.log`:

```
[GCClient] Recv msg 7170 (k_EMsgGCReadyUpStatus), 21 bytes
```

Она приходит, когда лобби матча создано и игрок ждёт ответа. Размер сообщения
растёт по мере того, как игроки подтверждают готовность.

### Ложные срабатывания

`k_EMsgGCReadyUpStatus` прилетает **в любом** лобби, включая practice и кастомные
игры. Скрипт смотрит в скользящее окно из 120 последних строк лога: если рядом
есть `PracticeLobby`, `CustomGame` или `Practice` — срабатывание игнорируется.

В party-лобби, где кто-то жмёт «готов», уведомление тоже придёт, и отличить
такое от матчмейкинга по логу невозможно. Это осознанный размен: лучше уведомить
лишний раз, чем пропустить матч. Если шум мешает — понизь `NOTIFY_COOLDOWN` или
добавь свои маркеры в `IGNORE_IF_RECENT`.

## Параметры скрипта

В начале `dota_awtrix.py`:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `AWTRIX_HOST` | из `config.json` / `AWTRIX_IP` | адрес матрицы |
| `DOTA_GSI_PORT` | `42069` | порт, который слушает скрипт |
| `NOTIFY_COOLDOWN` | `30` | секунд между уведомлениями о матче |
| `APP_DURATION_MS` | `5000` | сколько висит каждый экран |
| `APP_PUSH_INTERVAL` | `1.0` | как часто обновляются экраны, сек |
| `DEBUG_CONSOLE` | `False` | `True` — писать весь лог Dota в `bridge.log` |
| `GSI_STALE_SEC` | `20` | если GSI молчит дольше, матч считается конченным |
| `RECENT_WINDOW` | `120` | строк лога для проверки маркеров practice |

## Отладка

```bash
# что сейчас на матрице
python list_apps.py

# что реально нарисовано — раскладка по пикселям
python show_screens.py
```

Скриншоты для документации (нужен Pillow из `requirements-dev.txt`):

```bash
python make_screenshots.py [адрес_матрицы]
```

Скрипт отправляет на матрицу подборки правдоподобных данных для каждого экрана,
снимает кадровый буфер и собирает PNG в `docs/screens/`. В конце удаляет
временные приложения, так что рабочую ротацию не портит.

`bridge.log` пишет всё: переключения ротации, найденные матчи, отброшенные ложные
срабатывания, ошибки. Полезные строки:

- `*** MATCH DETECTED` — сработал детектор
- `ignored (practice/custom)` — лобби отсеяно
- `rotation saved` / `rotation restored` — переключение ротации
- `gsi fields:` — какие поля реально приходят от Dota
- `[AWTRIX] reachable` / `[DOTA] console.log:` — результат проверок при старте

При старте скрипт один раз сохраняет `gsi_sample.json` — сырой payload GSI. Если
что-то показывает нули, сначала смотри туда.

Пример для PowerShell:

```powershell
Get-Content bridge.log -Tail 40
```

Для bash:

```bash
tail -n 40 bridge.log
```

## Ограничения

- Автопоиск Dota парсит `libraryfolders.vdf`; если Steam установлен нестандартно,
  задай `dota_dir` в `config.json`
- `console.log` Dota удаляет при выходе — это нормально, скрипт переоткроет файл
- Блок `building` требует перезапуска Dota после правки конфига
- Ротация восстанавливается из сохранённого списка: если переставить приложения
  вручную во время игры, после матча вернётся то, что было до
- Если `gsi_port` занят, скрипт не запустится и GSI будет молча работать в никуда
- Нужен доступ к AWTRIX по HTTP без аутентификации либо с корректными
  `authUser`/`authPass` — сейчас скрипт авторизацию не отправляет

## API AWTRIX-NG

Используемые маршруты, подробности в
[HTTP API v1](https://blueforcer.github.io/awtrix-ng/reference/http/) и
[payload](https://blueforcer.github.io/awtrix-ng/reference/payload/):

| Метод | Путь | Зачем |
|---|---|---|
| `POST` | `/api/v1/notifications` | «Принять», «GO», «GG» |
| `PUT` | `/api/v1/apps/pushed/{name}` | экраны KDA / фарм / база / смерть |
| `PUT` | `/api/v1/apps/order` | переключение ротации |
| `DELETE` | `/api/v1/apps/{name}` | убрать экран |

Формат payload, цвета, `draw`-команды и графики описаны в
[App & notification payload](https://blueforcer.github.io/awtrix-ng/reference/payload/).
Иконки можно взять из [AWTRIX Hub](https://awtrix.de).

## Лицензия

MIT