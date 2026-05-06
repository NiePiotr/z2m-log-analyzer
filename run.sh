#!/usr/bin/with-contenv bashio

MQTTHOST=$(bashio::services mqtt "host")
MQTTPORT=$(bashio::services mqtt "port")
MQTTUSER=$(bashio::services mqtt "username")
MQTTPASSWORD=$(bashio::services mqtt "password")

export MQTTHOST MQTTPORT MQTTUSER MQTTPASSWORD

PYTHONUNBUFFERED=1 exec python3 -m app
