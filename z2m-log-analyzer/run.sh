#!/usr/bin/with-contenv bashio

MQTTHOST=$(bashio::services mqtt "host" 2>/dev/null || echo "")
MQTTPORT=$(bashio::services mqtt "port" 2>/dev/null || echo "")
MQTTUSER=$(bashio::services mqtt "username" 2>/dev/null || echo "")
MQTTPASSWORD=$(bashio::services mqtt "password" 2>/dev/null || echo "")

if [ -z "$MQTTHOST" ]; then
    MQTTHOST=$(bashio::config "mqtt_host" "localhost")
    MQTTPORT=$(bashio::config "mqtt_port" "1883")
    MQTTUSER=$(bashio::config "mqtt_user" "")
    MQTTPASSWORD=$(bashio::config "mqtt_password" "")
    bashio::log.info "MQTT service not available, using manual config"
fi

export MQTTHOST MQTTPORT MQTTUSER MQTTPASSWORD

PYTHONUNBUFFERED=1 exec python3 -m app
