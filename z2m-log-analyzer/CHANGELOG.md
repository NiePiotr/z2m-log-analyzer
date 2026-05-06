# Changelog

## 0.2.0 (unreleased)

### Added
- Device detail view: expand any device row for sparkline chart, category/level breakdown, last seen time
- Translations: English (`en.yaml`) and Polish (`pl.yaml`)
- Documentation: README.md, DOCS.md, Lovelace dashboard preset
- Burst detection: binary sensor activates when >N events occur within M minutes

## 0.1.0 (2026-05-06)

Initial MVP release.

### Features
- MQTT log subscription from Zigbee2MQTT bridge/logging with auto-reconnect
- 13-category message classifier (failed_to_ping, publish_failed, device_announce, interview_*, device_joined/leave, nwk_error, coordinator_error, mqtt_error, ota_event, unknown)
- SQLite persistence with WAL mode, schema migrations, configurable retention (default 30 days)
- Time-window aggregation: 1m, 5m, 1h, 24h
- MQTT Discovery sensors for Home Assistant (errors/warnings 1h/24h, failed_to_ping)
- Optional raw event MQTT topic for advanced consumers (Node-RED, AppDaemon)
- Web dashboard with 5 tabs:
  - Overview: KPI cards + 24h category bar chart
  - Timeline: interactive multi-series chart with filters
  - Devices: ranked list with expandable device detail and sparklines
  - Events: searchable log table with CSV export
  - Settings: retention, sensor selection, raw events toggle
- Dark theme UI with Alpine.js + Chart.js
- Health check endpoint (DB size, MQTT status, over-limit warning)
- DB size limit enforcement (500 MB default) with UI warning
- Graceful shutdown with event queue draining
- Ingress proxy support (X-Ingress-Path)
- Multi-architecture Docker support (amd64, aarch64, armv7, armhf, i386)
- Bilingual documentation (EN/PL)
- 30 unit tests (parser + storage)
