#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "shrink-z80" / "scripts" / "production_reachability.py"


def listing(rows: list[tuple[int, str, str]]) -> str:
    """sjasmplus-style listing lines: (address, emitted bytes, source)."""
    return "".join("%4d+ %04X %-12s %s\n" % (n + 1, addr, data, src) for n, (addr, data, src) in enumerate(rows))


HOME = listing([
    (0x0000, "", "RESET:"),
    (0x0000, "CD 10 00", "        call USED"),
    (0x0003, "C3 00 00", "        jp RESET"),
    (0x0010, "", "USED:"),
    (0x0010, "3E 01", "        ld a,1"),            # no transfer: falls through into FALLS_INTO
    (0x0012, "", "FALLS_INTO:"),
    (0x0012, "C9", "        ret"),
    (0x0013, "", "AFTER_RET:"),                     # only reachable by fall-through, which ret stops
    (0x0013, "00 00", "        nop : nop"),
    (0x0015, "", "SLOT_ALIAS EQU VIA_ALIAS"),        # an alias: references through it are followed
    (0x0015, "", "TABLE:"),
    (0x0015, "00 00", "        dw SLOT_ALIAS"),
    (0x0017, "", "VIA_ALIAS:"),
    (0x0017, "76", "        halt"),                  # halt is not a transfer: falls into AFTER_HALT
    (0x0018, "", "AFTER_HALT:"),
    (0x0018, "C9", "        ret"),
    (0x0019, "", "    IFDEF LEGACY_ONLY"),
    (0x0019, "~", "SKIPPED:"),                       # a false IF block: not a label of this image
    (0x0019, "", "    ENDIF"),
    (0x0019, "", "MARKER_END:"),                     # same address as LIVE: one location, no own bytes
    (0x0019, "", "LIVE:"),
    (0x0019, "C9", "        ret"),
    (0x001A, "", "DEAD:"),
    (0x001A, "18 FE", "        jr DEAD"),
    (0x001C, "", "LAST:"),
])


class ProductionReachabilityTest(unittest.TestCase):
    def run_script(self, *args: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            lst = Path(tmp) / "home.lst"
            lst.write_text(HOME, encoding="utf-8")
            done = subprocess.run([sys.executable, str(SCRIPT), str(lst), *args],
                                  capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_reports_only_labels_no_path_reaches(self) -> None:
        out = self.run_script("--root", "RESET", "--root", "TABLE", "--root", "LIVE")
        dead = {line.split()[2]: int(line.split()[3]) for line in out.splitlines() if line.startswith("home")}
        self.assertEqual(dead, {"AFTER_RET": 2, "DEAD": 2, "LAST": 0})
        self.assertNotIn("SKIPPED", out)
        self.assertIn("unreachable bytes per image: {'home': 4}", out)

    def test_roots_below_an_address(self) -> None:
        out = self.run_script("--roots-below", "0x1")
        self.assertIn("TABLE", out)          # nothing references the table without its root
        self.assertNotIn(" USED ", out)

    def test_requires_a_root(self) -> None:
        done = subprocess.run([sys.executable, str(SCRIPT), "missing.lst"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
