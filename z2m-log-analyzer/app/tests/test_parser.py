import json
from pathlib import Path

import pytest

from app.parser import (
    COORDINATOR_ERROR,
    DEVICE_ANNOUNCE,
    DEVICE_JOINED,
    DEVICE_LEAVE,
    FAILED_TO_PING,
    INTERVIEW_FAILED,
    INTERVIEW_STARTED,
    INTERVIEW_SUCCESSFUL,
    MQTT_ERROR,
    NWK_ERROR,
    OTA_EVENT,
    PUBLISH_FAILED,
    UNKNOWN,
    parse_message,
)


@pytest.mark.parametrize(
    ("message", "category", "device"),
    [
        ("Failed to ping 'Kitchen sensor'", FAILED_TO_PING, "Kitchen sensor"),
        ("Publish 'set' 'state' to 'Hall light' failed: timeout", PUBLISH_FAILED, "set"),
        ("MQTT publish to zigbee2mqtt/Bridge failed with error: disconnected", PUBLISH_FAILED, None),
        ("Device 'Office plug' announced itself", DEVICE_ANNOUNCE, "Office plug"),
        ("Starting interview of '0x00158d0001a2b3c4'", INTERVIEW_STARTED, "0x00158d0001a2b3c4"),
        ("Interview of 'Garage sensor' failed: Error: Interview failed", INTERVIEW_FAILED, "Garage sensor"),
        ("Successfully interviewed 'Bedroom dimmer'", INTERVIEW_SUCCESSFUL, "Bedroom dimmer"),
        ("Device 'Garden switch' joined", DEVICE_JOINED, "Garden switch"),
        ("Device 'Shed contact' left the network", DEVICE_LEAVE, "Shed contact"),
        ("Network error: MAC_INDIRECT_TIMEOUT for 0x00124b0024abcdef", NWK_ERROR, "0x00124b0024abcdef"),
        ("SRSP - SYS - ping after 6000ms", COORDINATOR_ERROR, None),
        ("MQTT error: connection refused", MQTT_ERROR, None),
        ("OTA update available for 'Living room bulb'", OTA_EVENT, "Living room bulb"),
    ],
)
def test_parse_message_classifies_supported_categories(message, category, device):
    parsed = parse_message(message, "warning")

    assert parsed == {
        "category": category,
        "device": device,
        "level": "warning",
        "raw_message": message,
    }


def test_parse_message_falls_back_to_unknown():
    message = "Zigbee2MQTT started successfully"

    parsed = parse_message(message, "info")

    assert parsed["category"] == UNKNOWN
    assert parsed["device"] is None
    assert parsed["raw_message"] == message


def test_parse_message_extracts_quoted_device_for_unknown_category():
    parsed = parse_message("Message from 'Pantry motion' ignored", "debug")

    assert parsed["category"] == UNKNOWN
    assert parsed["device"] == "Pantry motion"


def test_parse_message_extracts_ieee_address_without_quotes():
    parsed = parse_message("Network error for device 0x00158d0009abcdef", "ERROR")

    assert parsed["category"] == NWK_ERROR
    assert parsed["device"] == "0x00158d0009abcdef"


def test_parse_message_normalizes_level_to_lowercase():
    parsed = parse_message("Failed to ping 'Kitchen sensor'", "  ERROR ")

    assert parsed["level"] == "error"


def test_parse_message_matches_case_insensitively():
    parsed = parse_message("mqtt DISCONNECT from broker", "WARNING")

    assert parsed["category"] == MQTT_ERROR
    assert parsed["level"] == "warning"


def test_sample_log_fixture_covers_all_categories():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_logs.json"
    entries = json.loads(fixture_path.read_text())

    categories = {parse_message(entry["message"], entry["level"])["category"] for entry in entries}

    assert categories == {
        FAILED_TO_PING,
        PUBLISH_FAILED,
        DEVICE_ANNOUNCE,
        INTERVIEW_STARTED,
        INTERVIEW_FAILED,
        INTERVIEW_SUCCESSFUL,
        DEVICE_JOINED,
        DEVICE_LEAVE,
        NWK_ERROR,
        COORDINATOR_ERROR,
        MQTT_ERROR,
        OTA_EVENT,
        UNKNOWN,
    }
