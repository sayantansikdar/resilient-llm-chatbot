import pytest

from app.simulation import InvalidSimulationHeader, parse_simulation_header, status_for_key


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, {}),
        ("", {}),
        ("key_1=429", {"key_1": 429}),
        ("key_1=429,key_2=500", {"key_1": 429, "key_2": 500}),
        (" key_1 = 502 , key_2=503 ", {"key_1": 502, "key_2": 503}),
        ("*=429", {"*": 429}),
    ],
)
def test_parse(raw, expected):
    assert parse_simulation_header(raw) == expected


@pytest.mark.parametrize("raw", ["key_1", "key_1=", "=429", "key_1=abc", "key_1=404", "key_1=200"])
def test_parse_rejects_bad_input(raw):
    with pytest.raises(InvalidSimulationHeader):
        parse_simulation_header(raw)


def test_wildcard_and_explicit_key():
    failures = {"*": 429, "key_2": 500}
    assert status_for_key(failures, "key_1") == 429
    assert status_for_key(failures, "key_2") == 500
    assert status_for_key({"key_1": 429}, "key_2") is None
