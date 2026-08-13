# Глубокий аудит iScan + NetworkUSB

Дата: 2026-08-13 (UTC)

| Репозиторий | Версия | Коммит, который читался |
|---|---|---|
| [chumafox/iScan](https://github.com/chumafox/iScan) | `0.2.0` → этот PR `0.2.1` | `23ccab9` + правки ниже |
| [chumafox/NetworkUSB](https://github.com/chumafox/NetworkUSB) | `0.1.0` | `4713afb` (`main`) |

Это сверка **текущего кода**, не трекера и не прошлых `AUDIT.md`. У NetworkUSB уже открыт PR с аудитом по более старому `main`, у iScan — PR с частичным hardening. Оба документа местами устарели (см. §2). Выводы здесь перепроверены по исходникам.

---

## 1. Резюме для владельца

```
iPhone ── USB ── shop Mac                         master Mac
                 usbmuxd                             iScan / pymobiledevice3
                 usbmuxd-agent ══ TLS + mux ══ usbmuxd-bridge
                 :8721                               UNIX socket
                                                     NetworkUSBMenu (супервизор)
```

NetworkUSB — прозрачный байтовый мультиплексор `usbmuxd`, не proxy Lockdown. Pair record и HostID живут на Mac мастера. «Доверять этому компьютеру?» нажимают на физическом iPhone в магазине. Копировать pair records с агента бессмысленно и опасно.

Архитектура правильная и уже проверена на железе. Продукт при этом всё ещё **рабочий прототип, который таскают в прод**.

| Слой | Балл | Комментарий |
|---|---:|---|
| Архитектура туннеля | 8/10 | Один TLS, N сессий, agent ≠ bridge ≠ iScan |
| iScan CLI / transport | 8/10 | Диалекты адреса, doctor/pair, JSON-lines, fail-soft |
| iScan данные | 6/10 | Каталог моделей догоняет 2026; SIM/FMI/vendor — эвристики |
| Корректность mux | 5/10 | Нет версий протокола, HOL на agent dispatch, мёртвые `_local_queues` |
| Безопасность NetworkUSB | 4/10 | TLS есть; TOFU, `/tmp`, токен в меню-баре и `config.json` |
| Надёжность WAN | 5/10 | Реконнект есть, сокет при этом уничтожается; heartbeat односторонний |
| Меню-бар / ops | 4/10 | Хардкод путей, токен в argv, парсинг `Report saved:` |
| Инсталлер / CI | 4/10 | Идея `.pkg` сильная; CI не соберёт пакет без вендоренных бинарей |
| Тесты | 5/10 | iScan: unit; NUSB: 35 happy-path; нет HOL/DoS/menubar |
| Готовность к сети магазинов | 4/10 | Один агент, ручной обмен IP+токеном по SSH |

Три главных риска:

1. **Безопасность.** Любой локальный пользователь мастера может получить удалённый iPhone (`/tmp/usbmuxd.sock` в общем каталоге). Токен живёт в `ps` и plaintext `~/.config/usbmuxd-bridge/config.json`. Первое TLS-соединение без `--expected-fingerprint` отдаёт токен MITM.
2. **WAN-отчёт.** Одна медленная usbmux-сессия в agent reader loop блокирует HEARTBEAT и соседние сессии. Меню-бар каждые 4 с делает `usbmux list` поверх того же туннеля. На LAN незаметно, на Tailscale userspace — «туннель жив, отчёт завис».
3. **Операционка.** Подключить магазин = SSH за токеном + руками прописать host. На 10+ точках это не масштабируется и провоцирует «скину токен в чат».

---

## 2. Что устарело в предыдущих аудитах

`PROBLEMS.md` и открытые PR описывают код *до* `8bd1992` / `9e99a57`. На текущем `main` NetworkUSB уже иначе:

| Утверждение в старых документах | Факт в `4713afb` |
|---|---|
| Сокет `chmod 0777` | Дефолт `--socket-mode 0700`. Путь всё ещё `/tmp/usbmuxd.sock` |
| `auth_str != token`, лог `auth_str[:20]` | Уже `secrets.compare_digest`, лог без секрета |
| Нет `--token-file` / `--expected-fingerprint` | Оба есть, fingerprint проверяется **до** AUTH |
| `_write_lock` держится на время `drain()` | `drain()` **снаружи** lock. HOL всё равно жив (см. §4.1) |
| Backoff не сбрасывается | Сброс после 5 с стабильного соединения. Jitter нет |
| `itertools.count` уйдёт за uint32 | Есть `SessionIdAllocator` |
| Cert/known_hosts пишутся напрямую | `tempfile` + `os.replace` (без `fsync` и lock) |
| PREFLIGHT требует живой iPhone | iPhone — warning, `usbmuxd` socket — всё ещё hard fail |
| SECURITY.md: «обязательный TLS 1.3» | Код: `minimum_version = TLSv1_2` |
| iScan collectors «конкурентные» | `gather()` + `Lock` — ложная конкурентность, см. §5.1 |

---

## 3. Инварианты, которые нельзя ломать

1. Для `pymobiledevice3` канонический UNIX-адрес — **голый абсолютный путь**. Строка `unix:/tmp/usbmuxd.sock` парсится как TCP host `unix`. iScan нормализует; сырой `pymobiledevice3`, banner bridge и README NetworkUSB — нет.
2. Сокет bridge должен быть **стабильным** на время жизни процесса. TLS reconnect не должен `unlink` файл, иначе `iscan report` получает `ENOENT` посередине.
3. Сокет — частный IPC (`0700` каталог, `0600`/`0700` файл), не мир в `/tmp`.
4. Токен не живёт в argv, plist, `config.json` mode 0644, логах и JSON-progress.
5. Первый TLS fingerprint принимается только после `--expected-fingerprint` или явного `--tofu` + TTY confirm. Авто-TOFU ≠ защита от MITM.
6. Один медленный usbmux-сеанс не имеет права блокировать HEARTBEAT и соседние сессии.
7. Меню-бар читает `iscan report --json-progress` (`{"event":"saved","path":"..."}`), а не локализованную строку `Report saved:`.
8. Pairing выполняется на мастере. Оператору магазина показывают «нажми Trust».
9. LockdownClient **не реентерабелен**. iScan не должен стартовать AFC и Diagnostics одновременно, даже когда HOL в туннеле закроют.

---

## 4. NetworkUSB — открытые находки

Код не менялся в этом PR (сессия привязана к iScan). Ниже — то, что надо чинить в `chumafox/NetworkUSB`.

### 4.1 P0 — HOL: agent dispatch + общий TCP

`BridgeClient._send_frame` берёт lock только вокруг `writer.write()`, `drain()` снаружи. Это лучше, чем писали раньше, но:

- в `AgentServer._handle_bridge_inner` central reader делает `await sess.writer.drain()` **прямо в цикле разбора фреймов**. Медленный usbmuxd / полный сокет одной сессии останавливает DATA других сессий, CLOSE и echo HEARTBEAT;
- на bridge `_agent_reader_loop` так же `drain()`-ит локального клиента в том же цикле;
- HEARTBEAT идёт через `_send_frame` и тот же TCP window;
- `self._local_queues: dict[int, asyncio.Queue[bytes]] = {}` объявлен и **нигде не используется** — незавершённый фикс per-session queue.

Нужно: reader только валидирует и кладёт в bounded queue; writer task на сессию; overflow закрывает только её; CLOSE/HEARTBEAT — отдельная маленькая очередь. Регрессии: one-way ≥64 MiB; две сессии, одна с медленным consumer; heartbeat не должен отставать больше чем на 1 интервал.

iScan 0.2.1 смягчает это со своей стороны: коллекторы идут **последовательно**, поэтому один `iscan report` больше не открывает AFC ∥ diagnostics. Меню-бар всё ещё поллит `usbmux list` каждые 4 с во время отчёта — это отдельный P0 на стороне Swift.

### 4.2 P0 — `/tmp/usbmuxd.sock` и unlink на reconnect

Дефолт `--socket-mode 0700` уже есть. Осталось:

- путь `/tmp/usbmuxd.sock` в общем каталоге: любой пользователь может unlink и подставить свой сокет (TOCTOU);
- `_start_unix_server` удаляет существующий файл без `stat.S_ISSOCK`;
- ошибка `chmod` глотается;
- `_teardown` при каждом реконнекте **удаляет** сокет — интеграционный тест это закрепляет (`assert not os.path.exists(bridge_sock)`);
- меню-бар и `scripts/nusb` хардкодят `/tmp/usbmuxd.sock` и **не передают** `--socket-path`.

Нужно: `$HOME/Library/Application Support/networkusb/` mode `0700`, сокет `0600`, не unlink на transient TLS drop, перед unlink проверять тип, писать тот же путь в `active.json` без префикса `unix:`.

### 4.3 P0 — токен в меню-баре, argv, config.json

Агент: `--token-file` + `compare_digest` — хорошо. LaunchDaemon-шаблон больше не кладёт секрет в plist.

Дыры, которые остались:

- меню-бар стартует bridge как `--token <secret>` — секрет в `ps`;
- `~/.config/usbmuxd-bridge/config.json` хранит токен, `saveConfig()` пишет без `0600`;
- в `NetworkUSBMenu.swift` зашит токен Tart VM `0f1cead0241a2580faa848c351a82a5f1cef945573e8a059e3d5ceba6f6c22cb`;
- `resolve_token()` только **предупреждает**, если файл шире `0600`;
- `secrets.compare_digest(a, b)` в Python 3.11+ **бросает `ValueError`**, если длины разные. Неверный токен другой длины не получает `FAIL\n`, а роняет handler. Нужна обёртка с выравниванием длины.

### 4.4 P0 — TOFU по умолчанию

`--expected-fingerprint` проверяется до AUTH — правильно. Без флага первое соединение молча пинит сертификат и сразу шлёт токен. Активный MITM на первом коннекте становится «известным хостом». README и SECURITY.md продают это как защиту от MITM.

Production-профиль: `--expected-fingerprint` обязателен; TOFU только с явным `--tofu` и печатью fingerprint на stderr.

### 4.5 P0 — контракт адреса `unix:/path`

Banner, лог bridge и README Quick Start:

```text
export USBMUXD_SOCKET_ADDRESS=unix:/tmp/usbmuxd.sock
```

Это ломает `pymobiledevice3` без iScan. `active.json` тоже пишет `unix:/path` — iScan понимает, остальные клиенты нет. Меню-бар уже передаёт голый путь в env. Docs и banner должны делать то же.

### 4.6 P1 — нет лимитов, односторонний heartbeat, протокол

- Нет `max_bridges` / `max_sessions` (рекомендация: 4 / 32). Handshake timeout у `start_server` по умолчанию 60 с — не unlimited, вопреки старым аудитам. `readline()` ограничен 64 KiB у `StreamReader`.
- Bridge шлёт HEARTBEAT, но **не проверяет echo** и не рвёт полуоткрытый туннель. TCP keepalive вешается только на listening sockets агента.
- Backoff без jitter; auth failure / fingerprint mismatch крутятся бесконечно как transient.
- Повторный CONNECT с тем же id перезаписывает сессию, не закрывая старую. Payload у CONNECT/CLOSE/HEARTBEAT не запрещён. `build_frame` не проверяет `MAX_PAYLOAD_SIZE`. DATA на неизвестную сессию отвечает CLOSE — можно зафлудить.
- `_handle_bridge_inner` в `finally` делает `await writer.wait_closed()` **без таймаута** (внешний handler ограничивает 1 с, но внутренний может зависнуть раньше).
- Нет SIGTERM: LaunchDaemon шлёт TERM, `asyncio.run` не превращает его в graceful stop.
- Агент слушает `0.0.0.0:8721`. С userspace Tailscale входящие из tailnet проксируются на localhost, но порт открыт и в LAN.
- `check_unix_socket_accessible()` импортируется и не используется: старт агента проверяет только `os.path.exists`.

### 4.7 P1 — меню-бар

Файл `menubar/NetworkUSBMenu/NetworkUSBMenu.swift` (~590 строк) — супервизор продукта, тестов нет.

| Проблема | Почему это важно |
|---|---|
| Не передаёт `--socket-path` / `--token-file` / `--expected-fingerprint` | Конфиг и реальный сокет разъезжаются |
| `Get Info` парсит `Report saved:` | Локаль / `--json-progress` ломают открытие отчёта |
| `queryDevices` ждёт JSON `pymobiledevice3 usbmux list` | `iscan list --json` имеет другую форму |
| Поллинг каждые 4 с во время отчёта | HOL + лишняя сессия |
| Auto-activate первого Tailscale peer | Можно подключиться не к тому магазину |
| Scan не проверяет, что `:8721` — это агент (кроме localhost) | Ложные серверы в меню |
| Хардкод `~/Projects/NetworkUSB` и `~/Projects/iScan` | У любого другого layout меню-бар мёртв |
| Нет сборки `.app` в репозитории | `nusb` требует заранее собранный бинарь |

### 4.8 P1 — инсталлер и CI

- Workflow `build-client-pkg.yml` вызывает `installer/build_client_pkg.sh`, который **требует** `installer/third_party/tailscaled/{arm64,amd64}/tailscaled`. Каталог в `.gitignore`. CI на чистом runner падает.
- `TS_AUTHKEY` зашивается в `postinstall` внутри `.pkg`. Кто угодно с пакетом до первого использования ключа входит в tailnet.
- `timeout 10 tailscale up` часто мало.
- `uv python install 3.14` — тот самый рантайм, где `serve_forever()` дедлочит. Агент уже не использует `serve_forever()`, но пин 3.14 хрупкий; достаточно `>=3.11`.
- Пакет не подписан и не нотаризован.
- Агент после установки слушает `0.0.0.0:8721` без ограничения на Tailscale interface.
- `postinstall` с `set -uo pipefail` **без** `-e`.

### 4.9 P2 — мелочи, которые стоит закрыть пакетом

- Нет `--version` у agent/bridge (трекер, пункт 19).
- Нет `uv.lock` / `uv tool install`.
- Нет CI на `pytest` при PR.
- `research/` и незавершённые скрипты висят в дереве.
- `generate_self_signed`: cert и key — два отдельных `os.replace`; краш между ними оставляет рассогласованную пару; существующие файлы не проверяются на соответствие.
- `known_hosts` без file lock и `fsync`.
- Нет версионирования mux-протокола. Любое изменение фрейма — breaking change без переговоров.

---

## 5. iScan — находки и что закрыто здесь

### 5.1 P0, закрыто — timeout коллектора считал ожидание lock

`collect_all()` делал `asyncio.gather` четырёх задач, каждая с `wait_for(..., timeout)` и общим `asyncio.Lock` вокруг Lockdown I/O. Таймаут включал время в очереди на lock. Через NetworkUSB `device_info` на 7 с при `--timeout 8` оставлял battery/storage/components ~1 с или ноль — они помечались `timeout`, не запустившись.

Это не теоретический баг: именно так выглядит «частичный отчёт без батареи» на Tailscale.

Фикс: коллекторы идут **последовательно**. Каждый получает полный timeout. Побочный эффект — один `iscan report` больше не открывает две usbmux-сессии сразу и меньше бьётся о HOL NetworkUSB. Регрессия: `test_slow_first_collector_does_not_starve_later_ones`.

### 5.2 Закрыто в этом PR

- Все команды экспортируют `USBMUXD_SOCKET_ADDRESS` / `PYMOBILEDEVICE3_USBMUX` из `_resolve_cli_transport` (раньше — только `report`).
- Убран global `PYMOBILEDEVICE3_USERSPACE=1` на import `components`.
- `doctor` предупреждает о world-accessible сокете и не открывает lockdown на каждое устройство (`details=False`).
- Каталог моделей вынесен в `catalog.py` (iPhone 8 … 17 / Air / 17e). `iPhone18,4` — **iPhone Air**, не «17 Air».
- `report --json` пишет sidecar рядом с HTML.
- Vendor prefix в HTML помечен как inferred, не как факт оригинальности.
- Классификация ошибок больше не считает `list index out of range` и голое слово `socket` транспортом. `SSLSocket … pairing` → `NOT_PAIRED`.
- Версия отчёта берётся из `iscan.__version__` (`0.2.1`).
- Jinja Environment кэшируется.
- `pymobiledevice3>=4,<5` — верхняя граница, чтобы мажор не приехал молча.
- Готовый workflow pytest + ruff на 3.11/3.12/3.13 лежит в [`docs/github-ci.yml`](docs/github-ci.yml). Скопируйте его в `.github/workflows/ci.yml` — у GitHub App этой сессии нет права `workflows`, поэтому файл нельзя было положить в `.github/` напрямую.

### 5.3 Что в iScan всё ещё эвристика (P2, не блокер)

- `COLOR_NAMES` — целые числа `DeviceColor` не являются стабильным enum на всех моделях. Не угадывать цвет лучше, чем угадать неправильно; оставить raw, если ключа нет в таблице.
- SIM lock: `kCTPostponementStatusActivated` + `Activated` → `no_restrictions` — **не** доказательство SIM-Free. Нельзя писать в отчёте «разлочен» как факт.
- FMI / Apple ID читаются из IORegistry `options`, если повезёт. Отсутствие поля ≠ Find My выключен.
- «SSD replaced» срабатывает только для `iPhone13,1` > 256 ГиБ. Это аномалия ёмкости, не доказательство замены платы. Не расширять таблицу догадками.
- `probe_transport` только open/close TCP/UNIX. Не шлёт usbmux `LIST_DEVICES`. Для doctor этого достаточно; ложный «ok» возможен, если слушает не usbmuxd.
- HTML CSP разрешает `script-src 'unsafe-inline'` ради переключателя темы. Для `file://` отчёта приемлемо; хеш скрипта был бы чище.
- Нет ретрая, если туннель моргнул посреди коллектора. После фикса сокета в NetworkUSB (не unlink на reconnect) это станет дешевле добавить.

### 5.4 Контракт, который iScan теперь держит

```text
iscan doctor [--json]          exit 0/2/3/4
iscan pair --wait [--json-progress]
iscan report --json-progress [--json] [--usbmux-address PATH]
iscan list --json
iscan info --json
iscan --version
```

Коды: `2` нет устройства, `3` не paired, `4` транспорт, `5` сбор/запись. JSON-lines не смешиваются с Rich. Человеческий вывод по-прежнему содержит `Report saved: /abs/path` для старых сборок меню-бара.

Адрес: CLI → `USBMUXD_SOCKET_ADDRESS` → `PYMOBILEDEVICE3_USBMUX` → `~/.cache/networkusb/active.json` (если pid жив и путь — сокет) → системный usbmuxd. Токен из metadata не читается и не пишется.

---

## 6. Производительность

| Место | Сейчас | Что делать |
|---|---|---|
| iScan collectors | Последовательно, 8 с каждый, worst case ~32 с | Нормально для отчёта. Не возвращать `gather` |
| NetworkUSB chunk | 64 KiB | Ок. Не мельчить |
| Mux HOL | Один `drain()` стопорит всех | Per-session queue, §4.1 |
| Меню-бар poll | `usbmux list` каждые 4 с | Пауза на время `Get Info`; лучше слушать usbmux listen |
| HTML render | Environment кэшируется в 0.2.1 | Готово |
| TLS | RSA-2048, TLS 1.2+ | Можно ECDSA P-256 / TLS 1.3 only, не срочно |
| Tailscale userspace | Лишний копипаст userspace networking | Для LAN-магазина — обычный Tailscale; userspace оставить как fallback без VPN-prompt |

Не делать сейчас: сжатие фреймов, HTTP API, переписка на Go/Rust, mTLS до закрытия P0.

---

## 7. Модель угроз (коротко)

| Атакующий | Что может | Контрмера |
|---|---|---|
| Сосед по LAN магазина | Подключиться к `:8721`, ждать TOFU первого bridge | Слушать только Tailscale IP / localhost + обязательный fingerprint |
| Локальный пользователь мастера | Открыть `/tmp/usbmuxd.sock`, говорить с чужим iPhone | Runtime-каталог 0700 + сокет 0600 |
| Локальный пользователь мастера | Прочитать токен из `ps` / `config.json` | `--token-file` 0600, меню-бар не кладёт токен в argv |
| MITM на первом коннекте | Получить токен, закрепиться в known_hosts | `--expected-fingerprint` обязателен |
| Владелец `.pkg` до активации ключа | Войти в tailnet | Одноразовый ключ + ephemeral + ACL теги `tag:shop` |
| Оператор магазина | Видит Trust-диалог, не видит данные отчёта | Ок. Отчёт остаётся на мастере |
| Получатель HTML | XSS через имя устройства | autoescape + CSP (уже есть) |

iScan сам по себе не слушает сеть и не хранит токены. Его риск — PII в HTML (UDID, IMEI, серийники, иногда Apple ID). Отчёты не должны уезжать в облако и в общий чат.

---

## 8. Дорожная карта

### Уже в этом PR (iScan 0.2.1)

Последовательные коллекторы, env на всех командах, doctor privacy, `--json` sidecar, каталог моделей, inferred vendors, CI, ужесточённые exit codes.

### Фаза A — NetworkUSB, 3–5 дней (не светить телефон)

1. Приватный runtime-dir + стабильный сокет (не unlink на reconnect).
2. Banner/README/`active.json`: голый путь, не `unix:`.
3. Меню-бар: `--socket-path`, `--token-file`, `--expected-fingerprint`; `chmod 0600` на config; выкинуть зашитый Tart-токен.
4. `--expected-fingerprint` обязателен без `--tofu`.
5. Обёртка над `compare_digest` для разной длины.

### Фаза B — WAN не зависает, ~неделя

1. Per-session bounded queue + writer task ( hol ). Незавершённые `_local_queues` — отправная точка.
2. Heartbeat echo timeout на bridge; TCP keepalive на accepted/outbound sockets.
3. Лимиты 4 bridge / 32 сессии; отказ 33-й без падения процесса.
4. Меню-бар: `iscan report --json-progress`, пауза poll на время отчёта.
5. Регрессии: 64 MiB one-way, две сессии, reconnect с живым сокетом, 32+1 сессия.

### Фаза C — сеть магазинов

1. Агент слушает только Tailscale / `--host`.
2. Инсталлер: не требовать вендоренный tailscaled в git **или** класть его; не пинить 3.14; подпись пакета.
3. Tailscale ACL + hostname `shop-<id>`; мастер не читает токен по SSH — агент печатает fingerprint, токен остаётся локально, bridge получает его из `--token-file`, который кладёт мастер один раз.
4. Несколько магазинов в меню без auto-connect к первому попавшемуся peer.

### Фаза D — по потребности

`--version`, метрики сессий, mTLS, ECDSA, listen-mode вместо poll, iPad-каталог, ретраи коллекторов.

---

## 9. Что сознательно не делалось

- Не переписывался relay NetworkUSB: сессия Arena привязана к ветке iScan.
- Не утверждается оригинальность комплектующих по читаемости серийника.
- Не добавлялся HTTP/GUI в iScan.
- Не копировались pair records между машинами.

---

## 10. Как проверять

```bash
# iScan (этот репозиторий)
pip install -e ".[dev]"
pytest -q
ruff check src tests

# NetworkUSB (отдельный репозиторий) — сегодня 35/35, этого мало
pytest tests/ -q
# После фазы B обязательно:
#   one-way ≥ 64 MiB, две сессии, reconnect с живым сокетом,
#   heartbeat timeout, token-file, expected-fingerprint mismatch,
#   32 сессии + отказ 33-й, iscan doctor --json через реальный сокет
```

Связка на железе:

```text
shop:  sudo usbmuxd-agent --token-file /etc/networkusb/token --foreground
master: usbmuxd-bridge --agent-host 100.x --token-file ~/.config/usbmuxd-bridge/token \
          --expected-fingerprint AA:BB:… \
          --socket-path "$HOME/Library/Application Support/networkusb/usbmuxd.sock"
        export USBMUXD_SOCKET_ADDRESS="$HOME/Library/Application Support/networkusb/usbmuxd.sock"
        iscan doctor
        iscan pair --wait
        iscan report --json-progress --json --open
```
