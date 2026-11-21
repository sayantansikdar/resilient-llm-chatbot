"""Parsing for the X-Simulate-Failure test header.

    X-Simulate-Failure: key_1=429
    X-Simulate-Failure: key_1=429,key_2=500
    X-Simulate-Failure: *=429
"""

ALLOWED_STATUSES = {429, 500, 502, 503}
WILDCARD = "*"


class InvalidSimulationHeader(ValueError):
    pass


def parse_simulation_header(raw: str | None) -> dict[str, int]:
    """Return {key_id or '*': status}. Empty/missing header -> {}."""
    if raw is None or not raw.strip():
        return {}

    failures: dict[str, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key_id, sep, status = pair.partition("=")
        key_id, status = key_id.strip(), status.strip()
        if not sep or not key_id or not status.isdigit():
            raise InvalidSimulationHeader(f"expected <key_id>=<status>, got {pair!r}")
        code = int(status)
        if code not in ALLOWED_STATUSES:
            allowed = ", ".join(str(s) for s in sorted(ALLOWED_STATUSES))
            raise InvalidSimulationHeader(f"status {code} not supported (use one of {allowed})")
        failures[key_id] = code
    return failures


def status_for_key(failures: dict[str, int], key_id: str) -> int | None:
    """An explicit key entry wins over the wildcard."""
    if key_id in failures:
        return failures[key_id]
    return failures.get(WILDCARD)
