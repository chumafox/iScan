# Руководство по диагностике iOS-устройств из консоли (альтернатива 3uTools)

---

## 1\. Основные консольные утилиты

* [**libimobiledevice**](https://libimobiledevice.org/) — кроссплатформенный набор утилит на C для работы с iOS по USB и сети ([GitHub libimobiledevice](https://github.com/libimobiledevice/libimobiledevice)).  
* [**pymobiledevice3**](https://github.com/doronz88/pymobiledevice3) — библиотека и CLI-утилита на Python 3 с поддержкой протоколов и туннелей для iOS 17+.

---

## 2\. Работа через NetworkUSB и проверка транспорта

Если iPhone подключён к другому Mac, `NetworkUSB` пробрасывает его usbmuxd как локальный UNIX-сокет. Для `pymobiledevice3` и iScan нужен **голый путь** без префикса `unix:`:

```bash
export USBMUXD_SOCKET_ADDRESS=/absolute/path/to/usbmuxd.sock
iscan doctor
iscan pair --wait
iscan report --open
```

iScan также принимает `unix:/path`, `unix:///path` и `host:port` через `--usbmux-address`, но нормализует их перед вызовом pymobiledevice3. Pair record создаётся на Mac, где запущен iScan; оператор должен нажать «Доверять» на физическом устройстве.

Для интеграции с меню-баром используйте машиночитаемый контракт:

```bash
iscan report --json-progress
```

Он печатает JSON Lines (`start`, `connected`, `service`, `saved`, `error`) и не смешивает их с Rich-выводом.

## 3\. Команды для получения параметров (аналоги данных 3uTools)

### 2.1. Системная информация и идентификаторы

Вывод модели, версии iOS, IMEI, ECID, UDID, MAC-адресов Wi-Fi и Bluetooth.

* **Через `libimobiledevice`:**  
    
  \# Текстовый вывод всех ключей  
    
  ideviceinfo  
    
  \# Вывод в формате XML/plist  
    
  ideviceinfo \-x  
    
* **Через `pymobiledevice3`:**  
    
  pymobiledevice3 lockdown info

### 2.2. Состояние и параметры аккумулятора

Считывание числа циклов зарядки, проектной и текущей емкости, а также серийного номера аккумулятора.

* **Запрос домена батареи через `libimobiledevice`:**  
    
  ideviceinfo \-q com.apple.mobile.battery  
    
* **Мониторинг через `pymobiledevice3`:**  
    
  pymobiledevice3 diagnostics battery monitor

**Ключевые параметры:**

* `CycleCount` — количество циклов перезарядки.  
* `DesignCapacity` — заводская проектная емкость (мАч).  
* `FullChargeCapacity` — текущая максимальная емкость (мАч).  
* `BatterySerial` / `GasGauge` — серийный номер контроллера аккумулятора.

### 2.3. Серийные номера комплектующих (MobileGestalt)

Считывание серийных номеров материнской платы, экрана, камер и биометрических модулей.

* **Через `libimobiledevice` ([справка idevicediagnostics](https://linuxcommandlibrary.com/man/idevicesyslog)):**  
    
  idevicediagnostics mobilegestalt MainboardSerialNumber CoverboardSerialNumber RearFacingCameraModuleSerialNumber FrontFacingCameraModuleSerialNumber  
    
* **Через `pymobiledevice3`:**  
    
  pymobiledevice3 diagnostics mobilegestalt MainboardSerialNumber CoverboardSerialNumber RearFacingCameraModuleSerialNumber FrontFacingCameraModuleSerialNumber

**Ключи MobileGestalt:**

* `MainboardSerialNumber` / `MLBSerialNumber` — материнская плата.  
* `CoverboardSerialNumber` / `RawPanelSerialNumber` — дисплейный модуль.  
* `RearFacingCameraModuleSerialNumber` — основная (задняя) камера.  
* `FrontFacingCameraModuleSerialNumber` — фронтальная камера.  
* `MesaSerialNumber` — модуль Touch ID / Face ID.

---

## 4\. Рекомендации по разработке собственного инструмента

### Сравнение подходов

| Подход | Сложность | Рекомендация |
| :---- | :---- | :---- |
| **Писать всё с нуля (USB/usbmuxd)** | Очень высокая | ❌ Нецелесообразно (высокая трудоемкость реализации протоколов и шифрования). |
| **Форкать готовые инструменты** | Средняя | ⚠️ Неоптимально для сбора аппаратных серийников (проекты вроде [tidevice3](https://github.com/codeskyblue/tidevice3) ориентированы на автотесты). |
| **Собственный CLI/TUI на базе [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)** | Низкая | ✅ **Оптимальный выбор**: готовность за 1–2 вечера, кроссплатформенность, чистый Python API. |

---

## 5\. Примеры готовых скриптов

### Вариант A: Python-скрипт (`pymobiledevice3` \+ `rich`)

**Установка зависимостей:**

pip install pymobiledevice3 rich

**Код скрипта (`ios_diag.py`):**

from pymobiledevice3.lockdown import create\_using\_usbmux

from pymobiledevice3.services.diagnostics import DiagnosticsService

from rich.console import Console

from rich.table import Table

console \= Console()

def get\_device\_report():

    \# Подключение к устройству

    lockdown \= create\_using\_usbmux()

    all\_info \= lockdown.all\_values

    

    \# Запрос серийных номеров через MobileGestalt

    diag\_service \= DiagnosticsService(lockdown)

    gestalt\_keys \= \[

        'MainboardSerialNumber',

        'CoverboardSerialNumber',

        'RearFacingCameraModuleSerialNumber',

        'FrontFacingCameraModuleSerialNumber'

    \]

    gestalt\_info \= diag\_service.mobilegestalt(gestalt\_keys)

    \# Оформление таблицы

    table \= Table(title="Диагностический отчет iOS")

    table.add\_column("Параметр", style="cyan")

    table.add\_column("Значение", style="magenta")

    table.add\_row("Устройство", str(all\_info.get("ProductType")))

    table.add\_row("Версия iOS", str(all\_info.get("ProductVersion")))

    table.add\_row("Серийный номер", str(all\_info.get("SerialNumber")))

    table.add\_row("IMEI", str(all\_info.get("InternationalMobileEquipmentIdentity")))

    table.add\_row("Плата (MLB SN)", str(gestalt\_info.get("MainboardSerialNumber")))

    table.add\_row("Дисплей (SN)", str(gestalt\_info.get("CoverboardSerialNumber")))

    table.add\_row("Задняя камера (SN)", str(gestalt\_info.get("RearFacingCameraModuleSerialNumber")))

    table.add\_row("Фронтальная камера (SN)", str(gestalt\_info.get("FrontFacingCameraModuleSerialNumber")))

    console.print(table)

if \_\_name\_\_ \== "\_\_main\_\_":

    get\_device\_report()

### Вариант B: Bash-скрипт (`libimobiledevice`)

**Код скрипта (`ios_diag.sh`):**

\#\!/usr/bin/env bash

echo "=== IOS DEVICE DIAGNOSTIC REPORT \==="

echo "Model:      $(ideviceinfo \-k ProductType)"

echo "iOS:        $(ideviceinfo \-k ProductVersion)"

echo "Serial:     $(ideviceinfo \-k SerialNumber)"

echo "IMEI:       $(ideviceinfo \-k InternationalMobileEquipmentIdentity)"

echo "Wi-Fi MAC:  $(ideviceinfo \-k EthernetAddress)"

echo "BT MAC:     $(ideviceinfo \-k BluetoothAddress)"

echo "------------------------------------"

echo "=== BATTERY INFO \==="

ideviceinfo \-q com.apple.mobile.battery

echo "------------------------------------"

echo "=== COMPONENT SERIALS \==="

idevicediagnostics mobilegestalt MainboardSerialNumber CoverboardSerialNumber RearFacingCameraModuleSerialNumber FrontFacingCameraModuleSerialNumber  
