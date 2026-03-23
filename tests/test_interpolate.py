"""
Tests for the interpolation helper in client/client.py.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

import pytest
from client import _interpolate
from state import PlayerState


class TestInterpolate:
    def test_empty_buffer_returns_none(self):
        assert _interpolate([], time.time()) is None

    def test_single_entry_returns_it(self):
        s = PlayerState(pos_x=5.0)
        result = _interpolate([(1000.0, s)], 1000.0)
        assert result is not None
        assert result.pos_x == pytest.approx(5.0)

    def test_interpolates_between_two_samples(self):
        a = PlayerState(pos_x=0.0, pos_z=0.0)
        b = PlayerState(pos_x=10.0, pos_z=10.0)
        buf = [(1000.0, a), (1001.0, b)]
        result = _interpolate(buf, 1000.5)
        assert result is not None
        assert result.pos_x == pytest.approx(5.0, abs=0.1)
        assert result.pos_z == pytest.approx(5.0, abs=0.1)

    def test_clamps_to_last_when_past_end(self):
        a = PlayerState(pos_x=0.0)
        b = PlayerState(pos_x=10.0)
        buf = [(1000.0, a), (1001.0, b)]
        result = _interpolate(buf, 1002.0)
        # Should use latest sample (b)
        assert result is not None
        assert result.pos_x == pytest.approx(10.0)

    def test_clamps_to_first_when_before_start(self):
        a = PlayerState(pos_x=2.0)
        b = PlayerState(pos_x=8.0)
        buf = [(1000.0, a), (1001.0, b)]
        result = _interpolate(buf, 999.0)
        # t clamps to 0 → returns a
        assert result is not None
        assert result.pos_x == pytest.approx(2.0)

    def test_simultaneous_samples_returns_later(self):
        """When both samples have the same timestamp, dt ≈ 0, return b."""
        s = PlayerState(pos_x=7.0)
        buf = [(1000.0, s), (1000.0, s)]
        result = _interpolate(buf, 1000.0)
        assert result is not None

    def test_multiple_samples_picks_correct_bracket(self):
        samples = [(float(i), PlayerState(pos_x=float(i * 10))) for i in range(5)]
        # target_ts = 2.5 should fall between samples[2] and samples[3]
        result = _interpolate(samples, 2.5)
        assert result is not None
        assert result.pos_x == pytest.approx(25.0, abs=0.5)
