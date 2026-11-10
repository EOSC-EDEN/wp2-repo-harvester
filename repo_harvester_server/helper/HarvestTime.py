from datetime import datetime, timezone


def harvest_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def datetime_literal(timestamp):
    return {"@value": timestamp, "@type": "xsd:dateTime"}


def literal_value(value):
    if isinstance(value, dict):
        value = value.get('@value')
    return value if isinstance(value, str) and value else None


def display_timestamp(value):
    text = literal_value(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        return parsed.strftime('%Y-%m-%d %H:%M') + ' (server time)'
    return parsed.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
