from __future__ import annotations

from gramshelf.security import hash_password, new_api_token, verify_password


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_password_minimum_and_api_token() -> None:
    try:
        hash_password("too short")
    except ValueError as exc:
        assert "12" in str(exc)
    else:
        raise AssertionError("short password was accepted")

    assert new_api_token().startswith("gs_")
