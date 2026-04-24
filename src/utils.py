import re


def get_tier(message):
    m = message.lower()
    if "checkin" in m or "check-in" in m or "check in" in m:
        match = re.match(".*(t\\d+).*", m)
        if match is not None:
            return match.group(1).upper()
    return "unknown"
