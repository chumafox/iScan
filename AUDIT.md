# Глубокий аудит связки iScan + NetworkUSB

Дата: 2026-08-13 (UTC)  
Репозитории: [chumafox/iScan](https://github.com/chumafox/iScan) `0.2.0` и [chumafox/NetworkUSB](https://github.com/chumafox/NetworkUSB) `0.1.0` (main @ `9e99a57`).

Этот документ — сверка **текущего кода**, а не трекера. `PROBLEMS.md` в NetworkUSB частично устарел: F-03/F-04/F-07/F-09/F-10/F-11 уже частично закрыты, но README и меню-бар всё ещё учат опасному контракту.

## 1. Что это за система

```
iPhone ── USB ── shop Mac                     master Mac
                 usbmuxd                         iScan / pymobiledevice3
                 usbmuxd-agent ══ TLS/mux ══ usbmuxd-bridge
                                              private UNIX socket
```

NetworkUSB — **прозрачный байтовый мультиплексор usbmuxd**, не proxy Lockdown. Pair record и HostID живут на Mac мастера. «Доверять этому компьютеру?» появляется на физическом iPhone в магазине.

Следствие, которое нельзя потерять: копировать pair records с агента бессмысленно и опасно. Диагностика всегда идёт от идентичности мастера.

## 2. Состояние на сегодня

| Слой | Оценка | Комментарий |
|---|---|---|
| iScan transport/CLI | Хорошо | Диалекты адреса, doctor/pair, JSON-lines, fail-soft collectors, atomic HTML |
| iScan данные | Средне | Каталог моделей догоняет 2026; SIM/FMI/vendor — эвристики |
| NetworkUSB протокол/reconnect | Средне+ | F-01/F-07 закрыты; нет HOL-изоляции и лимитов |
| NetworkUSB security | Слабо для production | TOFU по умолчанию, `/tmp` socket, токен в меню-баре |
| Совместный контракт | Хрупкий | README/banner/nusb всё ещё печатают `unix:/path` |
| Тесты/CI | iScan: unit; NUSB: 35 happy-path | Нет WAN/HOL/DoS/регрессий сокета |

## 3. Архитектурные инварианты

1. Для pymobiledevice3 канонический UNIX-адрес — **голый абсолютный путь**. Строка `unix:/tmp/usbmuxd.sock` парсится как TCP host `unix`, port мусор. iScan это нормализует; сырой `pymobiledevice3` и меню-бар — нет.
2. Сокет bridge должен быть **стабильным** на время жизни процесса: TLS reconnect не должен `unlink` файл, иначе `iscan report` получает `ENOENT` посередине.
3. Сокет — частный IPC (`0700` каталог, `0600`/`0700` файл), не `/tmp` + world-access.
4. Токен не живёт в argv, plist, `config.json`, логах и progress events.
5. Первый TLS fingerprint принимается только после `--expected-fingerprint` или явного подтверждения. Авто-TOFU ≠ защита от MITM.
6. Один медленный usbmux-сеанс не имеет права блокировать HEARTBEAT и соседние сессии.
7. Меню-бар читает `iscan report --json-progress`, а не локализованную строку `Report saved:`.

## 4. NetworkUSB — что реально открыто

Сверка с `src/networkusb/**` на main. Статусы `PROBLEMS.md` в скобках, если они расходятся с кодом.

### P0 — ломает безопасность или WAN-диагностику

**F-06 HOL (открыто).**  
`BridgeClient._send_frame` держит общий `_write_lock` на время `await writer.drain()`. Agent в central dispatch делает `await sess.writer.drain()` прямо в reader loop. HEARTBEAT идёт через тот же lock. Один клиент, который не читает (или медленный AFC), ставит весь туннель, включая `iscan report` и watchdog.

Нужно: central reader только валидирует и кладёт в bounded per-session queue; отдельный writer task на сессию; overflow закрывает только её; control-фреймы (CLOSE/HEARTBEAT) — отдельная очередь.

Нет регрессионного теста на one-way ≥64 MiB и на две параллельные сессии с медленным consumer.

**F-02 TOFU (частично).**  
`--expected-fingerprint` проверяется **до** AUTH — это правильно. Но без флага первое соединение молча пинит сертификат и сразу шлёт токен. Активный MITM на первом коннекте становится «известным хостом». README всё ещё продаёт это как защиту от MITM.

Production-профиль: `--expected-fingerprint` обязателен; TOFU только с явным `--tofu` и печатью fingerprint на stderr/TTY confirm.

**F-03 путь сокета (частично).**  
Дефолт `--socket-mode 0700` уже есть. Дефолтный путь всё ещё `/tmp/usbmuxd.sock` в общем каталоге: любой локальный пользователь может unlink и подставить свой сокет (TOCTOU). `_start_unix_server` удаляет существующий файл без `S_ISSOCK`. Ошибка `chmod` глотается. `_teardown` при каждом реконнекте **удаляет** сокет — интеграционный тест это даже закрепляет (`assert not os.path.exists(bridge_sock)`).

Нужно: `$HOME/Library/Application Support/networkusb/` (mode `0700`), сокет `usbmuxd.sock` `0600`, не unlink на transient TLS drop, перед unlink проверять тип.

**F-04 токен (частично).**  
`--token-file` есть, plist больше не кладёт секрет в argv. Осталось:

- сравнение `auth_str[5:] != self.token` вместо `secrets.compare_digest`;
- лог `auth_str[:20]` при FAIL — префикс секрета;
- `resolve_token` только **предупреждает** о mode ≠ 0600;
- меню-бар стартует bridge с `--token` из `~/.config/usbmuxd-bridge/config.json` — секрет в JSON + `ps`.

**Контракт адреса (открыто, документация).**  
Banner bridge и README:

```text
export USBMUXD_SOCKET_ADDRESS=unix:/tmp/usbmuxd.sock
```

Это ломает pymobiledevice3 без iScan. `nusb` и меню-бар уже передают голый путь в env — хорошо, но docs учат обратному. В `active.json` поле `socket` пишется как `unix:/path`; iScan это понимает, другие клиенты — нет.

### P1 — надёжность туннеля

| ID | Статус | Суть |
|---|---|---|
| F-05 | открыто | Нет лимитов handshake/bridge/sessions/очередей. 4 MiB payload × N сессий. |
| F-08 | открыто | Bridge шлёт heartbeat, **не** проверяет echo. Half-open туннель выглядит живым, UNIX-сокет остаётся. TCP keepalive вешается на listen-сокеты агента, не на accepted/outbound. |
| F-09 | частично | Backoff сбрасывается после 5s uptime. Нет jitter. Fingerprint mismatch и неверный токен ретраятся вечно. |
| F-10 | частично | `SessionIdAllocator` и uint32 check в `build_frame` есть. Нет: запрет payload на CONNECT/CLOSE/HEARTBEAT, `session_id==0` для heartbeat, отказ повторного CONNECT без close старой сессии, cap payload в `build_frame`, антифлуд CLOSE на unknown DATA. |
| F-11 | частично | `os.replace` есть, `fsync`/file lock нет. cert.pem и key.pem пишутся двумя replace — не транзакция. Существующая пара не проверяется на соответствие. |
| F-12 | открыто | `check_unix_socket_accessible` не используется. Agent стартует, если путь `exists()`, даже если это обычный файл. |
| Reconnect socket | открыто | `_connect_and_serve` в `finally` зовёт `_teardown()` → unlink socket + delete `active.json`. iScan в середине сбора видит мёртвый endpoint. |
| LaunchDaemon | частично | Токен убран из plist. Осталось: bind `0.0.0.0`, нет ожидания `/var/run/usbmuxd`, нет SIGTERM/health, путь бинаря — плейсхолдер. |
| Меню-бар | открыто | Парсит `Report saved:`; не передаёт `--socket-path`/`--token-file`/`--expected-fingerprint`; `device_cmd` ждёт JSON pymobiledevice3, не `iscan list --json`. |
| Инсталлер | риск | `TS_AUTHKEY` вшивается в postinstall. Пакет unsigned/не notarized. Токен генерируется на клиенте — ок, но мастер читает его по SSH. |

### P2 — качество и продукт

- Нет CI на PR (есть только ручной `build-client-pkg`).
- Нет `--version` / `status` (число сессий, fingerprint, uptime).
- RSA-2048 + self-signed; лучше ECDSA P-256, в перспективе mTLS.
- `research/` в дереве — шум для релиза.
- Один агент / несколько bridge «вроде работает», не тестировалось.
- Agent не различает shop-id: мастер не видит, **какой** магазин на том конце, кроме IP.

## 5. iScan — находки и что уже закрыто здесь

### Уже было сделано в 0.2

- Нормализация `unix:` / `tcp:` / `host:port`.
- Приоритет CLI → env → `active.json` (stale pid/socket отбрасывается) → system.
- `doctor` / `pair --wait` / `--json-progress` / стабильные exit codes 2–5.
- Fail-soft collectors + timeout + `collection[]` / `issues[]`.
- Atomic HTML + Jinja autoescape + CSP + provenance транспорта.
- `list` не фильтрует только `USB`.
- `False` для `IsCharging` больше не теряется.

### Найдено при этом аудите и исправлено в этой ветке

| Баг | Почему важно | Фикс |
|---|---|---|
| `apply_environment` вызывался только из `report` | Fallback для старого pymobiledevice3 без `usbmux_address=` ломал `info`/`list`/`doctor`/`pair` | Все команды резолвят транспорт через один helper |
| Четыре collector'а били в один Lockdown параллельно | `start_service` не реентерабелен; на NetworkUSB это выглядит как мёртвый туннель | `asyncio.Lock` вокруг lockdown I/O, timeout остаётся per-collector |
| `PYMOBILEDEVICE3_USERSPACE=1` на import `components` | Глобальный side-effect для всего процесса | Убран |
| Каталог моделей обрывался на iPhone 16 | В магазине уже 16e / 17 / Air / 17e | `iscan.catalog` |
| `classify_connection_error("socket")` и `list index out of range` | Pairing/SSL и случайный IndexError становились «нет транспорта / нет устройства» | Уже маркеры |
| `iscan_version` захардкожен в модели | Расхождение с пакетом | Берётся из `__version__` |
| Vendor prefix в HTML как факт | Техник принимает Samsung/LG как доказательство | Подпись «inferred from serial prefix» |
| Нет машиночитаемого полного отчёта | Меню-бар/учёт вынуждены парсить HTML | `iscan report --json` пишет sidecar |
| `doctor` не смотрел mode сокета | 0777 NetworkUSB сокет выглядел healthy | Check `socket_privacy` |
| `list`/`doctor` открывали lockdown на каждое устройство | Лишние сессии через WAN | `details=False` в doctor |

### Что в iScan ещё стоит сделать (не в этом диффе)

**Данные (магазинная ценность).**

- SIM lock / FMI — сейчас эвристики (`kCTPostponementStatusActivated` + Activated = «no_restrictions» даёт ложные SIM-Free). Нужен честный `unknown` по умолчанию и отдельный сигнал только из явных ключей.
- Activation Lock / Find My часто **не** торчат в lockdown. Не обещать iCloud Lock, если нет IORegistry/`fm-activation-locked`.
- iPad / Watch / iPod catalog.
- IMEI Luhn, нормализация MAC, проверка длины серийника.
- Больше storage SKU для anomaly-check (сейчас только 12 mini 256).
- Опциональные коллекторы: crash reports, screenshot, syslog tail, installed profiles. Не тащить их в дефолтный WAN-report.

**Надёжность.**

- Общий deadline на `report` (сейчас 4 × timeout при сериализации).
- Retry одного collector'а при `BrokenPipe`/`IncompleteRead` (типичный transient reconnect).
- `probe_transport` сейчас только TCP/UNIX connect. Лучше слать usbmux `LIST_DEVICES` — иначе любой listener на пути выглядит healthy.
- Не глотать все исключения в `close_async` молча — хотя бы debug log.

**Продукт.**

- `iscan report --format html|json` без обязательного HTML, если нужен только sidecar.
- Сравнение двух отчётов (до/после ремонта).
- Красные флаги: FMI enabled, SIM locked, battery < 80%, missing MLB serial — отдельный summary block.
- Локализация CLI, не только HTML.

**Инфра.**

- CI добавлен (`.github/workflows/test.yml`). Дальше: pin pymobiledevice3 minor, mypy, интеграционный job с mock NetworkUSB.
- Нет LICENSE в обоих репозиториях — для внутреннего магазинного софта всё равно стоит зафиксировать.

## 6. Контракт, который надо держать в обоих репо

```text
# bridge (мастер)
usbmuxd-bridge \
  --agent-host 100.x.y.z \
  --token-file ~/.config/usbmuxd-bridge/token \
  --expected-fingerprint AA:BB:... \
  --socket-path "$HOME/Library/Application Support/networkusb/usbmuxd.sock"

export USBMUXD_SOCKET_ADDRESS="$HOME/Library/Application Support/networkusb/usbmuxd.sock"
iscan doctor --json
iscan pair --wait --json-progress
iscan report --json-progress --json --open
```

`active.json` (пишет bridge, читает iScan) — только hint:

```json
{
  "pid": 1234,
  "socket": "/absolute/path/usbmuxd.sock",
  "agent_host": "100.64.0.7",
  "agent_port": 8721,
  "fingerprint": "AA:BB:...",
  "version": "0.1.0"
}
```

Никогда не класть туда token. Предпочтительна голая форма `socket`, не `unix:`.

Меню-бар:

- `report_cmd = ["iscan", "report", "--json-progress", "--usbmux-address", socket]`
- открывать файл из события `{"event":"saved","path":"..."}`
- `device_cmd` либо `iscan list --json`, либо оставить pymobiledevice3, но не смешивать схемы
- `--token-file` + `--expected-fingerprint`, не `--token`

## 7. Дорожная карта (рекомендуемый порядок PR)

Не мешать relay rewrite с CLI/docs.

1. **NetworkUSB hotfix (1 день):** дефолтный private runtime dir; не unlink socket на reconnect; banner/README/`active.json` без `unix:`; `compare_digest`; убрать `auth_str[:20]`; `--token-file` в меню-баре; `--expected-fingerprint` required или `--tofu`.
2. **NetworkUSB F-06 (отдельный PR):** per-session queues + writer tasks + тесты one-way 64 MiB и slow-consumer.
3. **NetworkUSB limits + heartbeat echo (F-05/F-08):** 4 bridge, 32 sessions, 10s handshake, 4 MiB queue, echo timeout на bridge.
4. **Меню-бар:** JSON-lines iScan, pair UX («попросите нажать Доверять»), не парсить HTML.
5. **iScan данные:** честный unknown для SIM/FMI, iPad catalog, report summary flags, retry on BrokenPipe.
6. **Инсталлер:** не вшивать долгоживущий Tailscale key; notarize; healthcheck агента после postinstall.
7. **Совместный integration job:** mock usbmuxd → agent → bridge → `iscan doctor --json` / `iscan report --json`.

## 8. Как проверять

iScan (этот checkout):

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

Перед релизом связки — на двух Mac:

- `iscan doctor --json` через живой bridge;
- `iscan pair --wait` и Trust на физическом телефоне;
- `iscan report --json-progress --json` при параллельном `pymobiledevice3 usbmux list`;
- оборвать agent на 10s: сокет на мастере **остаётся**, report либо ретраится, либо даёт exit 4, но не висит;
- второй локальный пользователь **не** должен подключиться к сокету bridge.

## 9. Сознательно не делалось здесь

Код NetworkUSB в эту ветку не переносился: сессия привязана к `arena/019ff947-iscan`. Параллельный docs-PR NetworkUSB (`arena/019ff90d-networkusb`) закрывает баннер/docs; ядро relay всё ещё ждёт отдельного PR.
