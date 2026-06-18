"""`rogue scan` emits the same shareable breach card as `rogue try` (gated by --no-card)."""

from __future__ import annotations

import argparse
import sys

from rogue.cli import _emit_scan_card


class _StubReport:
    target = "my-bot (anthropic/claude-opus-4-8)"
    breach_rate = 0.4
    n_tests = 10
    n_breaches = 4

    @property
    def top_attack(self):
        return "DAN / Persona Jailbreak"

    def families_covered(self):
        return ["dan_persona", "role_hijack"]


def test_scan_emits_card(tmp_path, capsys):
    args = argparse.Namespace(no_card=False, json=False, judge="calibrated", out_dir=str(tmp_path / "c"))
    _emit_scan_card(_StubReport(), args, sys.stdout)
    out = capsys.readouterr().out
    assert "shareable card saved" in out
    assert list((tmp_path / "c").glob("breach-card*")), "expected a breach-card file"


def test_scan_no_card_flag_skips(tmp_path, capsys):
    args = argparse.Namespace(no_card=True, json=False, judge="quick", out_dir=str(tmp_path / "c"))
    _emit_scan_card(_StubReport(), args, sys.stdout)
    assert "shareable card" not in capsys.readouterr().out
    assert not (tmp_path / "c").exists()


def test_scan_json_skips_card(tmp_path, capsys):
    args = argparse.Namespace(no_card=False, json=True, judge="quick", out_dir=str(tmp_path / "c"))
    _emit_scan_card(_StubReport(), args, sys.stdout)
    assert "shareable card" not in capsys.readouterr().out
