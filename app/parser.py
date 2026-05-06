import re

FAILED_TO_PING = "failed_to_ping"
PUBLISH_FAILED = "publish_failed"
DEVICE_ANNOUNCE = "device_announce"
INTERVIEW_STARTED = "interview_started"
INTERVIEW_FAILED = "interview_failed"
INTERVIEW_SUCCESSFUL = "interview_successful"
DEVICE_JOINED = "device_joined"
DEVICE_LEAVE = "device_leave"
NWK_ERROR = "nwk_error"
COORDINATOR_ERROR = "coordinator_error"
MQTT_ERROR = "mqtt_error"
OTA_EVENT = "ota_event"
UNKNOWN = "unknown"

CLASSIFICATION_RULES: list[tuple[str, str]] = [
    (FAILED_TO_PING, r"Failed to ping '(?P<device>[^']+)'") ,
    (PUBLISH_FAILED, r"Publish .* failed|MQTT publish.*error"),
    (DEVICE_ANNOUNCE, r"Device '(?P<device>[^']+)' announced"),
    (INTERVIEW_STARTED, r"Starting interview of '(?P<device>[^']+)'") ,
    (INTERVIEW_FAILED, r"Interview.*failed|Interview of '(?P<device>[^']+)' failed"),
    (INTERVIEW_SUCCESSFUL, r"Successfully interviewed '(?P<device>[^']+)'") ,
    (DEVICE_JOINED, r"Device '(?P<device>[^']+)' joined"),
    (DEVICE_LEAVE, r"Device '(?P<device>[^']+)' left the network|left the network"),
    (NWK_ERROR, r"MAC_INDIRECT_TIMEOUT|SOURCE_ROUTE_FAILURE|Network error"),
    (COORDINATOR_ERROR, r"NCP Fatal Error|Coordinator.*failed|SRSP.*after \d+ms"),
    (MQTT_ERROR, r"MQTT.*(error|disconnect|failed)"),
    (OTA_EVENT, r"OTA (update|upgrade|query)"),
]

_COMPILED_CLASSIFICATION_RULES = [
    (category, re.compile(pattern, re.IGNORECASE))
    for category, pattern in CLASSIFICATION_RULES
]
_QUOTED_DEVICE_PATTERN = re.compile(r"'([^']+)'")
_IEEE_ADDRESS_PATTERN = re.compile(r"0x[0-9a-f]{16}", re.IGNORECASE)


def parse_message(message: str, level: str) -> dict:
    raw_message = message or ""

    for category, pattern in _COMPILED_CLASSIFICATION_RULES:
        match = pattern.search(raw_message)
        if match:
            return {
                "category": category,
                "device": _extract_device(raw_message, match),
                "level": _normalize_level(level),
                "raw_message": raw_message,
            }

    return {
        "category": UNKNOWN,
        "device": _extract_device(raw_message),
        "level": _normalize_level(level),
        "raw_message": raw_message,
    }


def _extract_device(message: str, match: re.Match | None = None) -> str | None:
    if match and "device" in match.groupdict() and match.group("device"):
        return match.group("device")

    quoted_match = _QUOTED_DEVICE_PATTERN.search(message)
    if quoted_match:
        return quoted_match.group(1)

    address_match = _IEEE_ADDRESS_PATTERN.search(message)
    if address_match:
        return address_match.group(0)

    return None


_VALID_LEVELS = {"error", "warning", "info", "debug"}

def _normalize_level(level: str) -> str:
    lvl = (level or "").strip().lower()
    return lvl if lvl in _VALID_LEVELS else "info"
