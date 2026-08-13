from __future__ import annotations

from iscan.catalog import commercial_name


def test_recent_iphone_identifiers():
    assert commercial_name("iPhone17,5") == "iPhone 16e"
    assert commercial_name("iPhone18,3") == "iPhone 17"
    assert commercial_name("iPhone18,1") == "iPhone 17 Pro"
    assert commercial_name("iPhone18,2") == "iPhone 17 Pro Max"
    assert commercial_name("iPhone18,4") == "iPhone Air"
    assert commercial_name("iPhone18,5") == "iPhone 17e"
    assert commercial_name("iPhone12,1") == "iPhone 11"


def test_unknown_identifier_is_preserved():
    assert commercial_name("iPhone99,1") == "iPhone99,1"
    assert commercial_name(None) is None
