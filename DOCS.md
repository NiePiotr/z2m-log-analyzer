# Z2M Log Analyzer — User Documentation

## Overview

Z2M Log Analyzer is a Home Assistant add-on that monitors your Zigbee network health by analyzing Zigbee2MQTT logs in real time.

It subscribes to `zigbee2mqtt/bridge/logging` via MQTT, classifies every message, and aggregates errors and warnings into time windows. The results are shown in a built-in web dashboard and exposed as Home Assistant sensors.

## Dashboard

The web UI has five tabs:

### Overview
Shows KPI cards with error and warning counts for the last hour and 24 hours. A bar chart breaks down categories for the last 24 hours. Auto-refreshes every 60 seconds.

### Timeline
Interactive line chart with:
- Window selector (1m, 5m, 1h, 24h)
- Category and level filters
- Time range presets (1h, 6h, 24h, 7d, 30d)
- Zoom via Chart.js time scale

### Devices
Ranked list of all devices by event count. Click any device to expand:
- Total event count and last seen time
- Sparkline chart showing activity over the selected time range
- Category and level breakdowns

### Events
Searchable, filterable log of all classified events. Supports:
- Filters by level, category, device
- Pagination
- CSV export

### Settings
Runtime configuration:
- Retention period (1-365 days)
- Raw events MQTT topic toggle
- Sensor selection
- Database size and MQTT connection status

## Home Assistant Integration

Sensors appear automatically via MQTT Discovery. Available sensors:

| Sensor | Description |
|--------|-------------|
| `sensor.z2m_errors_1h` | Total errors in last hour |
| `sensor.z2m_errors_24h` | Total errors in last 24 hours |
| `sensor.z2m_warnings_1h` | Total warnings in last hour |
| `sensor.z2m_warnings_24h` | Total warnings in last 24 hours |
| `sensor.z2m_failed_to_ping_1h` | Failed pings in last hour |

Sensors use `state_class: total_increasing`, so Home Assistant long-term statistics track them automatically.

### Automation examples

Alert when ping failures spike:
```yaml
alias: Z2M ping alert
trigger:
  - platform: numeric_state
    entity_id: sensor.z2m_failed_to_ping_1h
    above: 5
action:
  - service: notify.mobile_app_my_phone
    data:
      title: Zigbee alert
      message: >
        {{ trigger.to_state.state }} ping failures detected
```

## Message Categories

| Category | Pattern |
|----------|---------|
| `failed_to_ping` | Device did not respond to ping |
| `publish_failed` | MQTT publish to device failed |
| `device_announce` | Device announced itself to coordinator |
| `interview_started` | Coordinator started device interview |
| `interview_failed` | Device interview failed |
| `interview_successful` | Device interviewed successfully |
| `device_joined` | New device joined network |
| `device_leave` | Device left the network |
| `nwk_error` | Network layer error (MAC timeout, route failure) |
| `coordinator_error` | Coordinator/NCP error |
| `mqtt_error` | MQTT broker communication error |
| `ota_event` | OTA firmware update event |
| `unknown` | Fallback for unrecognized messages |

## Troubleshooting

**No sensors in HA**: Verify MQTT broker is running and `publish_sensors` is configured. Restart add-on to re-send discovery configs.

**High CPU**: Set Z2M log level to `warning` or `error`. Reduce retention days.

**DB too large**: The add-on prunes old data automatically. Check `/api/health` for size warning. Restart to trigger VACUUM.
