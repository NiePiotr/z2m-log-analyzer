# Z2M Log Analyzer

Home Assistant add-on: real-time log analysis for Zigbee2MQTT. Classify, aggregate, chart — find unstable devices before they fail.

## Features

- **Real-time log ingestion** via MQTT (`zigbee2mqtt/bridge/logging`)
- **13 categories**: failed_to_ping, publish_failed, device_announce, interview_*, device_join/leave, network errors, coordinator errors, MQTT errors, OTA events
- **Time-window aggregation**: 1m, 5m, 1h, 24h
- **MQTT Discovery sensors** for Home Assistant automations
- **Interactive dashboard**: timeline charts, device ranking with sparklines, event log with CSV export
- **Low footprint**: targets <100 MB RAM, <5% CPU on Raspberry Pi 4
- **Multi-arch**: amd64, aarch64, armv7, armhf, i386

## Quick start

1. Add this repository to your Home Assistant add-on store
2. Install **Z2M Log Analyzer**
3. Start — sensors appear automatically via MQTT Discovery
4. Open the web UI from the HA sidebar

## Configuration

```yaml
base_topic: zigbee2mqtt
retention_days: 30
enable_raw_events: false
publish_sensors:
  - errors_1h
  - errors_24h
  - warnings_1h
  - warnings_24h
  - failed_to_ping_1h
log_level: info
db_max_size_mb: 500
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/events` | Paginated event list |
| `GET /api/events/export.csv` | CSV export |
| `GET /api/aggregates` | Time-series data |
| `GET /api/devices/ranking` | Device leaderboard |
| `GET /api/devices/{name}` | Device detail + sparkline |
| `GET /api/health` | Status, DB size, MQTT |

## Requirements

- Home Assistant OS or Supervised
- Zigbee2MQTT add-on with MQTT broker

## License

MIT
