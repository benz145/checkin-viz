def get_tier(message):
    match = re.match(".*(t\\d+).*", message.lower())
    if match is not None:
        return match.group(1).upper()
    return "unknown"

