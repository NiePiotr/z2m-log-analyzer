# Zigbee2MQTT Log Analyzer — specyfikacja projektu

Add-on do Home Assistant analizujący logi dodatku Zigbee2MQTT w poszukiwaniu warningów i errorów, agregujący je w okna czasowe i prezentujący w postaci wykresów oraz raportów. Cel: diagnostyka działania urządzeń i komunikacji w sieci Zigbee.

---

## 1. Cel projektu

Dostarczyć użytkownikom Home Assistanta narzędzie do długoterminowej analizy stabilności sieci Zigbee2MQTT, którego sam Z2M nie posiada. Konkretnie:

- Wykrywanie problematycznych urządzeń (najczęstsze "Failed to ping", "Publish failed", utraty połączenia).
- Identyfikacja wzorców czasowych (np. eskalacja błędów wieczorem przy obciążeniu Wi-Fi, burst po restarcie koordynatora).
- Wsparcie automatyzacji w HA (powiadomienia, gdy liczba błędów w oknie godzinnym przekroczy próg).
- Raporty historyczne (per urządzenie, per kategoria, per okno czasowe).

## 2. Motywacja — dlaczego nie sam Z2M

Zigbee2MQTT oferuje wyłącznie:
- Surowy podgląd logów we frontendzie (bez agregacji).
- Plik logu w `/share/zigbee2mqtt/log/` (rotowany, bez analizy).
- Konfigurowalne poziomy logowania (error / warning / info / debug).

Brakuje: agregacji, kategoryzacji per urządzenie, wykresów w czasie, alertowania, raportów historycznych. Wszystko, co próbują dziś rozwiązać użytkownicy ad-hoc skryptami `grep` i `awk`.

## 3. Wymagania funkcjonalne

| ID    | Wymaganie                                                                                            | Priorytet |
|-------|------------------------------------------------------------------------------------------------------|-----------|
| F-01  | Subskrypcja logów Z2M w czasie rzeczywistym przez MQTT (`zigbee2mqtt/bridge/logging`)               | MUST      |
| F-02  | Klasyfikacja każdego loga do kategorii (failed_to_ping, publish_failed, interview_failed, …)        | MUST      |
| F-03  | Ekstrakcja `friendly_name` lub IEEE z treści wiadomości                                              | MUST      |
| F-04  | Persystentne przechowywanie eventów w SQLite z konfigurowalną retencją (default 30 dni)             | MUST      |
| F-05  | Agregaty w oknach: 1 min / 5 min / 1 h / 24 h, per kategoria, per urządzenie, total                 | MUST      |
| F-06  | UI add-ona dostępne przez Ingress (autoryzacja Supervisora)                                          | MUST      |
| F-07  | Wykresy: timeline (multi-series), słupkowy (24 h), ranking urządzeń                                  | MUST      |
| F-08  | Filtrowany log eventów z eksportem CSV                                                               | MUST      |
| F-09  | Publikacja agregatów jako sensorów HA przez MQTT Discovery                                           | MUST      |
| F-10  | Konfiguracja w UI: retencja, lista kategorii do publikacji, progi alertowe                           | MUST      |
| F-11  | Opcjonalna publikacja surowych eventów na osobny topic MQTT (default OFF)                            | SHOULD    |
| F-12  | Wykrywanie burstów (np. >N errorów w <M minut)                                                       | SHOULD    |
| F-13  | Eksport raportu PDF / HTML                                                                           | NICE      |
| F-14  | Korelacja błędów z metadanymi urządzenia z `bridge/devices`                                          | NICE      |

## 4. Wymagania niefunkcjonalne

- **Multi-arch**: amd64, aarch64, armv7, armhf, i386 (dzięki bazowemu obrazowi).
- **Niski narzut**: aplikacja IO-bound, target <100 MB RAM, <5% CPU na RPi 4.
- **Resilience**: utrata połączenia z brokerem nie wywala procesu; backoff i auto-reconnect.
- **Kompatybilność**: HA OS i HA Supervised (klasyczne add-ony). Container/Core poza scope MVP.
- **Bezpieczeństwo**: brak zewnętrznych portów; cała komunikacja przez Supervisor + lokalny broker.

## 5. Architektura

```
┌─────────────────────────┐
│   Zigbee2MQTT add-on    │
│  publikuje na MQTT      │
│  zigbee2mqtt/bridge/    │
│         logging         │
└────────────┬────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────┐
│                  Z2M Log Analyzer (ten add-on)                │
│                                                                │
│  ┌──────────────┐   ┌────────┐   ┌─────────┐   ┌──────────┐  │
│  │ MQTT Consumer│──▶│ Parser │──▶│ Storage │──▶│Aggregator│  │
│  │  (aiomqtt)   │   │(regex) │   │(SQLite) │   │(60s tick)│  │
│  └──────────────┘   └────────┘   └─────────┘   └────┬─────┘  │
│                                       ▲              │        │
│                                       │              ▼        │
│                                  ┌────┴─────┐  ┌──────────┐  │
│                                  │  FastAPI │  │Publisher │  │
│                                  │   + UI   │  │(MQTT     │  │
│                                  │ (Ingress)│  │Discovery)│  │
│                                  └──────────┘  └────┬─────┘  │
└────────────────────────────────────────────────────┼─────────┘
                                                     │
                                                     ▼
                                       ┌─────────────────────────┐
                                       │  Home Assistant Core    │
                                       │  (sensory, automatyzacje)│
                                       └─────────────────────────┘
```

## 6. Stack techniczny

| Warstwa     | Wybór                                                  | Dlaczego                                                           |
|-------------|--------------------------------------------------------|--------------------------------------------------------------------|
| Język       | Python 3.12                                            | Domena IO-bound, znajomy w społeczności HA, dojrzały async         |
| Web/API     | FastAPI                                                | Async, typowanie, OpenAPI za darmo                                 |
| MQTT        | aiomqtt                                                | Async wrapper na paho, czyste API                                  |
| Storage     | SQLite (aiosqlite)                                     | Wbudowane, persistent przez `/data`, brak zewnętrznych zależności  |
| Frontend    | Vanilla HTML + Chart.js (lub ApexCharts)               | Bez build-stepu, prosty deploy, łatwa kontrybucja                  |
| Scheduler   | asyncio + APScheduler                                  | Tasking dla agregatora i retencji                                  |
| Baza Docker | `ghcr.io/hassio-addons/base-python`                    | Multi-arch, bashio, s6-overlay, utrzymywany przez core team HA     |
| Manifest    | `config.yaml` (Supervisor add-on schema)               | Ingress, deklaracja `services: ["mqtt:need"]`                      |

### Odrzucone alternatywy

- **Node.js**: technicznie OK, ale słabsza znajomość w społeczności HA dla integracji typu „analityka”.
- **Mojo**: świetny do AI/HPC, kompletnie nieadekwatny do IO-bound usługi sieciowej, niedojrzały ekosystem MQTT/web, pre-1.0.
- **Wpinanie się w bazę recordera HA**: anty-pattern. Schemat wewnętrzny, podatny na zmiany, locking issues, brak gwarancji stabilności.

## 7. Struktura projektu

```
zigbee2mqtt-log-analyzer/
├── config.yaml              # Manifest add-ona (Supervisor)
├── Dockerfile
├── build.yaml               # Multi-arch build config
├── run.sh                   # Entrypoint (bashio init + python -m app)
├── README.md
├── CHANGELOG.md
├── icon.png
├── logo.png
├── DOCS.md                  # Dokumentacja użytkownika (zakładka Documentation w UI)
├── translations/
│   ├── en.yaml
│   └── pl.yaml
└── app/
    ├── __init__.py
    ├── __main__.py          # python -m app
    ├── config.py            # Czytanie /data/options.json
    ├── main.py              # FastAPI bootstrap, lifespan, routing
    ├── mqtt_consumer.py     # Subskrypcja bridge/logging
    ├── parser.py            # Klasyfikacja + ekstrakcja device
    ├── storage.py           # SQLite: schema, queries, retencja
    ├── aggregator.py        # Okna czasowe, materialized aggregates
    ├── publisher.py         # MQTT Discovery dla HA + raw event topic
    ├── api/
    │   ├── __init__.py
    │   ├── events.py        # /api/events
    │   ├── aggregates.py    # /api/aggregates
    │   ├── devices.py       # /api/devices/ranking
    │   └── settings.py      # /api/settings
    ├── ui/
    │   ├── index.html
    │   ├── app.js
    │   ├── styles.css
    │   └── assets/
    └── tests/
        ├── test_parser.py
        ├── test_storage.py
        └── fixtures/
            └── sample_logs.json
```

## 8. Komponenty

### 8.1 MQTT Consumer (`mqtt_consumer.py`)

- Subskrybuje `zigbee2mqtt/bridge/logging` (konfigurowalny base topic).
- Payload: `{"level": "warning", "message": "...", "meta": {...}?}`.
- Auto-reconnect z exponential backoff (1s → 60s, max).
- Po starcie próbuje dociągnąć `zigbee2mqtt/bridge/devices` raz, by zbudować mapę `friendly_name → ieee_address` (dla normalizacji nazw między restartami).
- Publikuje eventy do wewnętrznej `asyncio.Queue` konsumowanej przez parser.

### 8.2 Parser (`parser.py`)

Pipeline przetwarzania pojedynczej wiadomości:

1. **Klasyfikacja** — lista regexów z priorytetami, pierwszy match wygrywa, fallback `unknown`.
2. **Ekstrakcja device** — wyłapanie `'<name>'`, `0x[0-9a-f]{16}`, mapowanie przez słownik z bridge/devices.
3. **Normalizacja level** — Z2M używa `error|warning|info|debug`, ujednolicić na te cztery.

Reguły kategoryzacji (pierwsza wersja, łatwa do rozszerzenia):

| Kategoria              | Wzorzec (uproszczony)                                                |
|------------------------|----------------------------------------------------------------------|
| `failed_to_ping`       | `Failed to ping '<device>'`                                          |
| `publish_failed`       | `Publish .* failed` lub `MQTT publish` + error                       |
| `device_announce`      | `Device '<device>' announced itself`                                 |
| `interview_started`    | `Starting interview of '<device>'`                                   |
| `interview_failed`     | `Interview of '<device>' failed`                                     |
| `interview_successful` | `Successfully interviewed '<device>'`                                |
| `device_joined`        | `Device '<device>' joined`                                           |
| `device_leave`         | `Device '<device>' left the network`                                 |
| `nwk_error`            | `MAC_INDIRECT_TIMEOUT`, `SOURCE_ROUTE_FAILURE`, `Network error`     |
| `coordinator_error`    | `NCP Fatal Error`, `Coordinator failed`, `SRSP - .* after \d+ms`    |
| `mqtt_error`           | `MQTT.*error`, `MQTT.*disconnect`                                    |
| `ota_event`            | `OTA update.*`                                                       |
| `unknown`              | (fallback)                                                           |

### 8.3 Storage (`storage.py`)

Schemat (SQLite, WAL mode):

```sql
CREATE TABLE events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,         -- unix timestamp ms
    level        TEXT NOT NULL,            -- error|warning|info|debug
    category     TEXT NOT NULL,
    device       TEXT,                     -- friendly_name lub ieee, NULL gdy nieprzypisane
    raw_message  TEXT NOT NULL,
    meta         TEXT                      -- JSON, opcjonalnie
);
CREATE INDEX idx_events_ts            ON events(ts);
CREATE INDEX idx_events_device_ts     ON events(device, ts);
CREATE INDEX idx_events_category_ts   ON events(category, ts);
CREATE INDEX idx_events_level_ts      ON events(level, ts);

CREATE TABLE aggregates (
    bucket_ts    INTEGER NOT NULL,         -- start okna (unix ms)
    window       TEXT NOT NULL,            -- '1m'|'5m'|'1h'|'24h'
    level        TEXT NOT NULL,
    category     TEXT NOT NULL,
    device       TEXT,                     -- NULL = total dla kategorii
    count        INTEGER NOT NULL,
    PRIMARY KEY (bucket_ts, window, level, category, device)
);

CREATE TABLE meta_kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

**Retencja**: task działający co 1 h kasuje `events` starsze niż `retention_days` z konfiguracji. Aggregates 1 m / 5 m mają krótszą retencję (np. 7 dni), 1 h / 24 h pełną.

### 8.4 Aggregator (`aggregator.py`)

- Tick co 60 s.
- Zlicza eventy z minionej minuty grupując po (level, category, device) → upsert do `aggregates` window=`1m`.
- Co 5 min agregat dla `5m`, co godzinę dla `1h`, co 24 h dla `24h`.
- Przy starcie odbudowuje stan z `events` (nie ufa pamięci po crashu).

### 8.5 Publisher (`publisher.py`)

**MQTT Discovery** — przy starcie wystawia konfiguracje sensorów:

```
homeassistant/sensor/z2m_log_analyzer/errors_1h/config
homeassistant/sensor/z2m_log_analyzer/errors_24h/config
homeassistant/sensor/z2m_log_analyzer/warnings_1h/config
homeassistant/sensor/z2m_log_analyzer/warnings_24h/config
homeassistant/sensor/z2m_log_analyzer/failed_to_ping_1h/config
... (lista konfigurowalna w UI)
```

State publikowany na `zigbee2mqtt_log_analyzer/state/<sensor_id>` co aktualizację agregatu.

**Opcjonalny raw event topic** (`enable_raw_events: true` w configu, default OFF):
- Topic: `zigbee2mqtt_log_analyzer/events`
- Payload: `{"ts": 1730000000000, "level": "warning", "category": "failed_to_ping", "device": "kitchen_motion", "message": "..."}`

### 8.6 UI / API

**Endpointy API** (FastAPI):

| Metoda | Ścieżka                              | Opis                                                       |
|--------|---------------------------------------|------------------------------------------------------------|
| GET    | `/api/events`                         | Paginowana lista eventów z filtrami (since, level, ...)    |
| GET    | `/api/aggregates`                     | Serie czasowe dla wybranej kategorii / okna / device       |
| GET    | `/api/devices/ranking`                | Top N urządzeń wg liczby eventów                           |
| GET    | `/api/categories/summary`             | Sumy per kategoria w wybranym oknie                        |
| GET    | `/api/settings`                       | Bieżąca konfiguracja                                       |
| POST   | `/api/settings`                       | Update konfiguracji runtime (retencja, sensory)            |
| GET    | `/api/export.csv`                     | Eksport CSV dla zakresu                                    |
| GET    | `/api/health`                         | Liveness/readiness, status MQTT                            |

**Zakładki UI**:

- **Overview** — KPI cards (errors 1h/24h, warnings 1h/24h, top device), 24-godzinny słupkowy.
- **Timeline** — wykres liniowy multi-series, zoom, range picker, filtry.
- **Devices** — ranking, sortowanie, szczegół urządzenia (sparkline, breakdown kategorii).
- **Events** — paginowany log z filtrami i eksportem.
- **Settings** — retencja, lista publikowanych sensorów, raw events toggle, progi alertowe.
- **Documentation** — render `DOCS.md`.

## 9. Konfiguracja add-ona

### 9.1 `config.yaml` (manifest Supervisora)

```yaml
name: Zigbee2MQTT Log Analyzer
version: "0.1.0"
slug: z2m_log_analyzer
description: Analiza logów Zigbee2MQTT z agregatami i wykresami
arch:
  - amd64
  - aarch64
  - armv7
  - armhf
  - i386
init: false
ingress: true
ingress_port: 8099
panel_icon: mdi:chart-line
panel_title: Z2M Log Analyzer
services:
  - mqtt:need
options:
  base_topic: zigbee2mqtt
  retention_days: 30
  enable_raw_events: false
  raw_events_topic: zigbee2mqtt_log_analyzer/events
  publish_sensors:
    - errors_1h
    - errors_24h
    - warnings_1h
    - warnings_24h
    - failed_to_ping_1h
  log_level: info
schema:
  base_topic: str
  retention_days: int(1,365)
  enable_raw_events: bool
  raw_events_topic: str
  publish_sensors:
    - str
  log_level: list(debug|info|warning|error)
```

### 9.2 Zmienne środowiskowe wstrzykiwane przez Supervisor

Z `services: ["mqtt:need"]` Supervisor podstawia automatycznie:
- `MQTTHOST`, `MQTTPORT`, `MQTTUSER`, `MQTTPASSWORD`

Czytane przez `bashio::services "mqtt"` w `run.sh` i przekazywane do procesu Pythona jako env.

## 10. Integracja z Home Assistant

Trzy ścieżki:

1. **Sensory MQTT Discovery** — automatycznie pojawiają się w HA, można ich używać w automatyzacjach, dashboardach, statystykach długoterminowych.
2. **Raw event topic** (opcjonalny) — dla zaawansowanych odbiorców (Node-RED, AppDaemon, własne integracje).
3. **UI w Lovelace** — add-on jest też klikalnym panelem w sidebar HA dzięki `panel_icon` + `panel_title`.

Pomocnicy (`input_number`, `counter`) **nie są zapisywane bezpośrednio** — zamiast tego user, jeśli chce, tworzy automatyzację reagującą na sensor MQTT i sam aktualizuje pomocnika. To zachowuje czystą separację: my wystawiamy dane, HA decyduje co z nimi zrobić.

## 11. Roadmap

### MVP (v0.1)

- [ ] `config.yaml` + Dockerfile + `run.sh`, "hello world" w UI przez Ingress.
- [ ] MQTT consumer + zapis surowy do SQLite.
- [ ] Parser z 5 najczęstszymi kategoriami (failed_to_ping, publish_failed, device_announce, interview_failed, unknown).
- [ ] Endpoint `/api/events` + tabela w UI.
- [ ] Endpoint `/api/aggregates` + wykres timeline w UI.
- [ ] MQTT Discovery dla 4 podstawowych sensorów (errors/warnings × 1h/24h).
- [ ] Retencja konfigurowalna (default 30 dni).

### v0.2

- [ ] Pełna lista kategorii (12).
- [ ] Ranking urządzeń + szczegół urządzenia.
- [ ] Eksport CSV.
- [ ] Konfiguracja runtime z UI (zapis do `options.json` przez Supervisor API).
- [ ] Tłumaczenia EN/PL.

### v0.3

- [ ] Wykrywanie burstów + alerty (sensor binary).
- [ ] Korelacja z `bridge/devices` (typ urządzenia, vendor).
- [ ] Raw event topic (opcjonalny).
- [ ] Dashboardy presety (Lovelace YAML do skopiowania).

### v1.0

- [ ] Eksport raportu PDF/HTML.
- [ ] Analizator trendów (regression / anomaly detection na agregatach).
- [ ] Publikacja w HACS / oficjalnym repo add-onów.

## 12. Decyzje techniczne — uzasadnienia

| Decyzja                                  | Wybór                          | Alternatywa odrzucona              | Powód                                                                          |
|------------------------------------------|--------------------------------|-------------------------------------|--------------------------------------------------------------------------------|
| Język                                    | Python 3.12                    | Node.js, Mojo, Go                  | Społeczność HA, dojrzały async, idealny do IO-bound                            |
| Źródło logów                             | MQTT `bridge/logging`          | Parsowanie pliku logu              | Real-time, bez problemów z dostępem do FS, brak lockingu                       |
| Storage                                  | Własny SQLite                  | DB recordera HA                    | Schemat HA jest wewnętrzny i może się zmienić; locking; nie pasuje do logów    |
| Baza Docker                              | hassio-addons/base-python      | python:3.12-alpine                 | Multi-arch, bashio, s6, gotowy CI                                              |
| Web framework                            | FastAPI                        | Flask, aiohttp                     | Async natywnie, OpenAPI, typowanie                                             |
| Frontend                                 | Vanilla HTML + Chart.js        | React/Vue                          | Brak build-stepu, prosty deploy, łatwa kontrybucja                             |
| Eksponowanie do HA                       | MQTT Discovery                 | Bezpośrednia manipulacja helperami | Czysta separacja, idiomatyczne dla HA, user kontroluje co się dzieje dalej     |
| Default raw events                       | OFF                            | ON                                 | Niegrzeczne wobec brokera, większość userów nie potrzebuje                     |

## 13. Otwarte pytania

- Czy dodać ścieżkę dla użytkowników bez MQTT (np. parsowanie pliku logu Z2M jako fallback)? → Prawdopodobnie nie w MVP, większość Z2M userów ma już skonfigurowany broker.
- Czy wspierać multi-instancję Z2M (różne `base_topic`)? → MVP: jedna instancja. v1.0: lista źródeł.
- Czy korzystać z statystyk długoterminowych HA (`state_class: total_increasing`) czy własna baza? → Sensory `total_increasing` dla liczników eskalacji + własna baza dla detali. Najlepsze z obu światów.
- Limit rozmiaru bazy SQLite — czy hard cap (np. 500 MB) jako safety net obok retencji czasowej? → Tak, MVP. Z alertem w UI.

## 14. Inspiracje i pokrewne projekty

- **Frigate** — wzorzec add-ona z bogatym UI i własną bazą, dobry przykład struktury.
- **AppDaemon** — alternatywne podejście do logiki opartej na zdarzeniach w HA.
- **Loki + Grafana** — alternatywa enterprise, ale wymaga osobnego stosu i jest poza scope HA-native.
- **Z2M Ember Helper** (`nerivec.github.io/z2m-ember-helper`) — narzędzie diagnostyczne dla driverów ember; źródło wiedzy o typach błędów na poziomie NCP.

---

**Status dokumentu**: draft v1, do akceptacji przed rozpoczęciem implementacji MVP.
