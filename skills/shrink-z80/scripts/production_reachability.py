#!/usr/bin/env python3
"""Production-image reachability over sjasmplus listings (candidate generator, not proof).

A routine that only legacy or test builds still reference -- because they share a source file with
the shipped image -- is dead in the shipped image, but a textual dead-code scan counts those
references. This walks the label graph of the listings of the images that actually ship:

* an edge from a global label to every identifier its code references (data tables included);
* an edge X -> Y for `X EQU Y` aliases, so references through an alias are followed;
* lines of false conditional blocks (sjasmplus marks them `~`) are ignored;
* precise fall-through: a label falls into the next label of the same image only when the last
  instruction before that next label is not an unconditional transfer (`ret`, `reti`, `retn`,
  `jp nn`, `jr nn`, `jp (hl/ix/iy)`). `halt` is not a transfer: execution resumes after it.

Roots are given explicitly (`--root`, `--root-prefix`, `--roots-below`). Purely numeric
references (a slot address written as a number, a computed `jp (hl)` target) are invisible, and an
`rst` that never returns is still treated as a call: verify every candidate by hand, then exclude
it from the production build with a define (not by deleting it, the other builds still use it).

  python3 production_reachability.py HOME.lst EXROM.lst --roots-below 0x100 \\
      --root-prefix V2_EXROM_ --root VM_OP_TABLE --root COLD_START

Output: one line per unreachable global label (image, address, name, bytes up to the next label)
and the total per image. Exit 0 = ran (candidates or not); 2 = usage / file error.
Measured use: ~170 bytes of legacy-only routines in a 16K HOME + 8K EXROM interpreter ROM pair.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

IDENT = re.compile(r"(?<![A-Za-z0-9_.$])([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)")
LINE = re.compile(r"\s*\d+\+*\s+([0-9A-F]{4})")
LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):?(\s|$)")
DIRECTIVES = {"IFDEF", "IFNDEF", "ENDIF", "ELSE", "INCLUDE", "DEFINE", "ORG", "ASSERT", "DS", "DB", "DW",
              "MACRO", "ENDM", "DEVICE", "SAVEBIN", "IF", "OUTPUT", "ALIGN", "DISPLAY", "DEFB", "DEFW", "DEFS"}
CONDITIONS = r"(z|nz|c|nc|po|pe|p|m)"
TERMINAL = re.compile(r"^(ret|reti|retn|jp\s+\((hl|ix|iy)\)|jp\s+[a-z_.$0-9+\-]+|jr\s+[a-z_.$0-9+\-]+)$")
CONDITIONAL = re.compile(r"^((jp|jr)\s+" + CONDITIONS + r"\s*,|ret\s+" + CONDITIONS + r"$)")


class Graph:
    def __init__(self) -> None:
        self.labels: dict[str, tuple[str, int]] = {}
        self.order: dict[str, list[tuple[int, str]]] = {}
        self.refs: dict[str, set[str]] = {}
        self.last: dict[str, str] = {}
        self.defined: dict[str, int] = {}   # definition order (the last label before code owns it)
        self.aliases: set[str] = set()      # names defined by EQU / DEFL / = (graph nodes, not code)

    def ref(self, src: str, text: str) -> None:
        for ident in IDENT.findall(text):
            self.refs.setdefault(src, set()).add(ident.split(".")[0])

    def parse(self, listing: Path, image: str) -> None:
        current = None
        seq: list[tuple[int, str]] = []
        for raw in listing.open(errors="replace"):
            line = raw.rstrip("\n")
            m = LINE.match(line)
            if not m:
                continue
            at = m.start(1)
            if line[at + 5:at + 6] == "~":          # a line of a false IF block: not assembled
                continue
            addr = int(m.group(1), 16)
            emitted = [b for b in line[at + 5:at + 17].split() if re.fullmatch(r"[0-9A-F]{2}", b)]
            code = line[at + 18:].split(";")[0]
            lm = LABEL.match(code) if code and not code[0].isspace() else None
            if lm and lm.group(1).upper() not in DIRECTIVES:
                name = lm.group(1)
                rest = code[len(lm.group(0)):].strip()
                op = rest.split()[0].upper() if rest else ""
                if op in ("EQU", "DEFL", "="):
                    self.aliases.add(name)
                    self.ref(name, rest[len(op):])
                    continue
                if op in ("MACRO", "ENDM"):
                    continue
                current = name
                self.defined[name] = len(self.defined)
                self.labels[name] = (image, addr)
                seq.append((addr, name))
                code = rest
            if current and code.strip():
                if emitted:
                    self.last[current] = " ".join(code.strip().lower().split())
                self.ref(current, code)
        self.order[image] = sorted(seq)

    def groups(self, image: str) -> list[tuple[int, list[str]]]:
        """Labels of one image grouped by address: labels sharing an address name the same code."""
        out: list[tuple[int, list[str]]] = []
        for addr, name in self.order[image]:
            if out and out[-1][0] == addr:
                out[-1][1].append(name)
            else:
                out.append((addr, [name]))
        return out

    def link_fallthrough(self) -> None:
        for image in self.order:
            grp = self.groups(image)
            for addr, names in grp:            # same address: one location, reachable through any name
                for x in names:
                    self.refs.setdefault(x, set()).update(n for n in names if n != x)
            for (_, names), (_, nxt) in zip(grp, grp[1:]):
                owners = [n for n in names if n in self.last]
                last = self.last[max(owners, key=self.defined.get)] if owners else ""
                if not (TERMINAL.match(last) and not CONDITIONAL.match(last)):
                    for n in names:
                        self.refs.setdefault(n, set()).update(nxt)

    def reachable(self, roots: set[str]) -> set[str]:
        nodes = self.labels.keys() | self.aliases
        seen: set[str] = set()
        stack = [r for r in roots if r in nodes]
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            stack.extend(r for r in self.refs.get(name, ()) if r in nodes and r not in seen)
        return seen

    def unreachable(self, seen: set[str]) -> list[tuple[str, int, str, int]]:
        out = []
        for image in self.order:
            grp = self.groups(image)
            for i, (addr, names) in enumerate(grp):
                if not any(n in seen for n in names):
                    nxt = grp[i + 1][0] if i + 1 < len(grp) else addr
                    out.append((image, addr, "/".join(names), nxt - addr))
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("listings", nargs="+", type=Path, help="sjasmplus listings of the shipped images")
    ap.add_argument("--root", action="append", default=[], help="a root label (repeatable)")
    ap.add_argument("--root-prefix", action="append", default=[], help="labels starting with this are roots")
    ap.add_argument("--roots-below", type=lambda v: int(v, 0), default=None,
                    help="labels below this address in the FIRST listing are roots (e.g. 0x100: RST/NMI vectors)")
    a = ap.parse_args(argv)
    if not (a.root or a.root_prefix or a.roots_below is not None):
        ap.error("give at least one of --root, --root-prefix, --roots-below")
    g = Graph()
    try:
        for listing in a.listings:
            g.parse(listing, listing.stem)
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 2
    g.link_fallthrough()
    first = a.listings[0].stem
    roots = {n for n in g.labels.keys() | g.aliases
             if n in a.root or n.startswith(tuple(a.root_prefix))
             or (a.roots_below is not None and n in g.labels and g.labels[n][0] == first
                 and g.labels[n][1] < a.roots_below)}
    totals: dict[str, int] = {}
    for image, addr, name, size in sorted(g.unreachable(g.reachable(roots))):
        totals[image] = totals.get(image, 0) + size
        print("%-12s %04X %-40s %d" % (image, addr, name, size))
    print("roots: %d; unreachable bytes per image: %s" % (len(roots), totals or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
