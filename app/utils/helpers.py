from datetime import datetime


def get_current_shift_id(now: datetime) -> str:
    """
    Simple shift logic:
    S1: 06:00–14:00
    S2: 14:00–22:00
    S3: 22:00–06:00
    """
    h = now.hour
    if 6 <= h < 14:
        return "S1"
    elif 14 <= h < 22:
        return "S2"
    return "S3"
