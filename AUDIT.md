# Глубокий аудит связки iScan + NetworkUSB

Дата аудита: 2026-08-13 (UTC)

## Контекст

Ссылка на предыдущий агентский диалог Arena открывается только после reCAPTCHA, поэтому исходный чат нельзя было надёжно прочитать через внешний fetch. Контекст был восстановлен из публичного `chumafox/NetworkUSB`, его ветки `arena/019ff90d-networkusb` и файла `AUDIT.md`, а затем сверён с исходниками iScan в этом репозитории. Это важно: выводы ниже основаны на коде, а не на предположении о том, как должен работать туннель.

NetworkUSB — прозрачный мультиплексор usbmuxd, а не proxy уровня Lockdown. На мастере iScan/pymobiledevice3 создаёт pair record и HostID. Следовательно, «Trust This Computer?» появляется на физическом iPhone в магазине, а доверие сохраняется на Mac мастера.

## Архитектура и главные риски

```text
shop Mac: iPhone ─ usbmuxd ─ agent ══ TLS/mux ══ bridge ─ private UNIX socket ─ iScan
```

| Приоритет | Риск в связке | Последствие |
|---|---|---|
| P0 | Общий `/tmp/usbmuxd.sock` с `0777` на bridge | Любой локальный пользователь мастера получает полный доступ к удалённому iPhone |
| P0 | TOFU NetworkUSB без обязательного fingerprint при первом соединении | MITM может получить токен до закрепления сертификата |
| P0 | Токен bridge в argv/config | Секрет виден через `ps` и резервные копии |
| P0 | HOL blocking в relay при одном медленном usbmuxd-сеансе | `iscan report` и heartbeat зависают через WAN |
| P1 | UNIX-сокет удаляется при реконнекте bridge | iScan получает `ENOENT/ECONNREFUSED` в середине работы |
| P1 | Bridge не подтверждает heartbeat echo | Полуоткрытый туннель выглядит рабочим |
| P1 | Нет лимитов сессий/handshake/очередей | DoS или неограниченное потребление ресурсов |
| P1 | Меню-бар парсит `Report saved:` | Локаль/формулировка ломает открытие отчёта |
| P1 | README NetworkUSB раньше рекомендовал `unix:/path` | pymobiledevice3 воспринимает `unix` как TCP host |
| P2 | iScan глушил исключения и собирал последовательно | Нельзя отличить «нет батареи» от мёртвого туннеля; WAN-отчёт висит без границы |
| P2 | HTML использовал локальные `file:///Users/...` и не включал autoescape | Отчёт не переносим; имя устройства могло испортить HTML |

Первые пункты должны закрываться в NetworkUSB: приватный стабильный socket lifecycle, `--token-file` у bridge, обязательный `--expected-fingerprint`, constant-time auth, per-session bounded queues и heartbeat. Ветка NetworkUSB уже содержит хороший журнал F-01…F-12; его нельзя считать закрытым только потому, что happy-path тест проходит.

## Что изменено в iScan

### 1. Единый transport contract

`iscan.transport`:

- принимает bare UNIX path, `unix:/path`, `unix:///path`, `tcp:host:port`, `tcp://host:port` и `host:port`;
- имеет приоритеты CLI → `USBMUXD_SOCKET_ADDRESS` → `PYMOBILEDEVICE3_USBMUX` → `~/.cache/networkusb/active.json` → системный usbmuxd;
- отбрасывает stale metadata и не читает/не хранит токены;
- передаёт один нормализованный адрес в API pymobiledevice3 и экспортирует обе env-переменные;
- `probe_transport()` проверяет сам endpoint до попытки Lockdown.

Это устраняет самый хрупкий контракт между NetworkUSB и iScan: разные диалекты адреса и ручной экспорт env.

### 2. Fail-soft collection

`collect_all()` теперь запускает device info, battery, AFC storage и components независимо, с timeout на каждый collector. Каждый отчёт содержит:

- `collection[name] = {status, duration_ms, fields}`;
- `issues[]` для timeout/отсутствующих optional services;
- transport provenance: socket kind/source, NetworkUSB agent и fingerprint.

Один недоступный IORegistry или battery domain больше не стирает серийник и базовую информацию. `lockdown` закрывается после `report`/`info`/`doctor`/`pair`.

### 3. Надёжность данных

- `False` для `IsCharging` больше не теряется из-за `or`;
- async и sync collectors используют одинаковую нормализацию чисел/bytes/bools;
- `list` больше не фильтрует только `USB`, поэтому не теряет remote/Wi-Fi mux devices;
- components запрашивает serials камер/платы через IORegistry и MobileGestalt fallback;
- storage ограничивает невозможные значения и имеет lockdown fallback;
- generated timestamp — timezone-aware UTC;
- имя файла отчёта санитизируется.

### 4. Операционный CLI-контракт

Добавлены:

```text
iscan doctor [--json]
iscan pair --wait [--json-progress]
iscan report --json-progress
iscan list --json
iscan info --json
iscan --version
```

Коды выхода стабильны: `2` нет устройства, `3` не paired, `4` транспорт недоступен, `5` ошибка сбора/записи. JSON-lines не смешиваются с Rich-выводом. Человеческий вывод всё ещё содержит `Report saved: /absolute/path` для старого NetworkUSBMenu.

### 5. Безопасный переносимый HTML

- Jinja autoescape включён;
- удалены machine-local watermark/image paths;
- CSP запрещает внешние ресурсы;
- HTML показывает transport/collection provenance и partial warnings;
- serial читаемости компонента не трактуется как доказательство оригинальности;
- отчёт пишется через temp + fsync + `os.replace`, чтобы меню-бар не открыл обрезанный файл.

## Контракт, который теперь нужно держать в обоих репозиториях

1. NetworkUSB создаёт приватный socket (`0600`) внутри приватного runtime-каталога и **не удаляет его при временном TLS reconnect**.
2. В supervisor передаётся именно этот путь:
   `USBMUXD_SOCKET_ADDRESS=/absolute/path`, без `unix:` для pymobiledevice3.
3. Bridge должен либо писать `~/.cache/networkusb/active.json` с `pid`, `socket`, `agent_host`, `agent_port`, `fingerprint`, либо меню-бар передаёт `--usbmux-address` явно.
4. Token не попадает в argv, JSON config, logs и progress events. Для bridge нужен `--token-file` с mode `0600`.
5. Первый TLS fingerprint принимается только после явного подтверждения/известного `--expected-fingerprint`; автоматический TOFU нельзя считать production MITM protection.
6. NetworkUSB relay изолирует slow session: bounded per-session queue + отдельный writer task; CLOSE/HEARTBEAT не должны ждать DATA другой сессии.
7. Меню-бар использует `iscan report --json-progress`, а не парсит локализованную строку.
8. Pairing выполняется на master Mac, а оператору магазина показывается явная инструкция нажать Trust.

## Проверка

В этом checkout:

```bash
PYTHONPATH=src pytest -q
```

Тесты не требуют подключённого iPhone: fixture проверяет EN/RU render и fallback collectors. Перед релизом связки необходимы интеграционные тесты NetworkUSB:

- one-way transfer не менее 64 MiB без обратного DATA;
- две параллельные сессии, одна с медленным consumer;
- reconnect с живым UNIX socket;
- heartbeat echo timeout на bridge;
- token-file и expected fingerprint;
- 32 сессии + отказ 33-й без падения bridge;
- `iscan doctor --json` через реальный `/tmp/usbmuxd.sock`.

## Что сознательно не делалось

Не переписывался NetworkUSB relay в этой ветке: сессия Arena привязана к `arena/019ff922-iscan`, а смена/публикация другой ветки запрещена. Код iScan и документированный contract подготовлены так, чтобы PR NetworkUSB мог быть отдельным и не смешивал большой relay diff с CLI/HTML изменениями.
