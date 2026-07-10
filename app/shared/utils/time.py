from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def utc_now_naive() -> datetime:
    return datetime.utcnow()


def format_iso(dt: datetime) -> str:
    return dt.isoformat()
