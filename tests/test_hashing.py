"""Tests for the deterministic cache hashing (plan 01 section 7, task F-5)."""

from __future__ import annotations

from pathlib import Path

from scan2plan.util.hashing import cache_key, hash_bytes, hash_file, hash_json


def test_hash_bytes_is_sha256() -> None:
    # sha256("abc") is a well-known constant.
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert hash_bytes(b"abc") == expected


def test_hash_json_key_order_independent() -> None:
    assert hash_json({"a": 1, "b": 2}) == hash_json({"b": 2, "a": 1})


def test_hash_json_changes_with_value() -> None:
    assert hash_json({"a": 1}) != hash_json({"a": 2})


def test_hash_file_matches_hash_bytes(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello world")
    assert hash_file(p) == hash_bytes(b"hello world")


def test_cache_key_order_independent_inputs() -> None:
    a = cache_key(inputs=["x", "y"], config_digest="c", code_version="0.1.0")
    b = cache_key(inputs=["y", "x"], config_digest="c", code_version="0.1.0")
    assert a == b


def test_cache_key_sensitive_to_each_component() -> None:
    base = cache_key(inputs=["x"], config_digest="c", code_version="0.1.0")
    assert base != cache_key(inputs=["x"], config_digest="d", code_version="0.1.0")
    assert base != cache_key(inputs=["x"], config_digest="c", code_version="0.2.0")
    assert base != cache_key(inputs=["z"], config_digest="c", code_version="0.1.0")
