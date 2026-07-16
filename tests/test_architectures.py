"""Tests for shipped writing architecture metadata."""

from __future__ import annotations

import pytest

from writer.explore import ARCHITECTURES, lookup_architecture


def test_architectures_md_parses_to_eight_entries() -> None:
    assert len(ARCHITECTURES) == 8
    assert all(spec.name and spec.short_description and spec.markdown for spec in ARCHITECTURES)


def test_lookup_architecture_known_returns_spec() -> None:
    spec = lookup_architecture("三幕结构")

    assert spec.name == "三幕结构"
    assert "铺垫" in spec.markdown


def test_lookup_architecture_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        lookup_architecture("不存在的架构")


def test_architectures_have_unique_names() -> None:
    names = [spec.name for spec in ARCHITECTURES]
    assert len(names) == len(set(names))


__all__ = []
