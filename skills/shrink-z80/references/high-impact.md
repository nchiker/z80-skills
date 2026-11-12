# Winner Pass

Start here for `scan`. Work these families in the order the census ranks
them for the pressure target. Each kept candidate must clear the materiality
threshold (user figure, else 30 B net). Put smaller ones in one tail line.

## 1. Overlay-only resident code -> move into that overlay

- Detect: census `[overlay_only]`. A group lists the routine plus its helpers
  that move with it (`with <caller>`).
- Accept only while resident is the pressure target: a move spends the
  destination overlay's margin. Once resident has room and overlays near their
  cap are the constraint, stop moving and work overlay headroom instead.
- Accept: every target's census agrees. Run it per linked map, because another
  target may call the routine from resident. The overlay keeps its cap, and
  moved helpers stay static in the overlay.
- Verify: callers in C and ASM (`rg` the symbol, `EXTERN`, `call`/`jp`,
  function tables). `[weak refs]` means a bare 16-bit match: check data tables.
  Host tests that stub the symbol, layering guards, overlay-state allowlists
  and ABI baselines usually need an intentional update.

## 2. Code dominated by an earlier gate -> delete the re-check

- Detect: for each early-return gate on a dispatch path (peer ready, transfer
  pending, busy, game state), `rg` the same predicate below it on every path
  from that gate.
- Accept: every caller path, in every `#if` target branch, passes the gate
  first. A stricter predicate the gate implies counts too
  (`!game_active || peer` after a `peer` gate).
- Verify: transition and parity tests. Test harnesses that call the inner
  function directly may depend on the re-check.

## 3. Compiler allocation budget -> one flag, every module

- Detect: SDCC builds without `--max-allocs-per-node`, or with a low value.
- Measure: in a disposable worktree, build at 20000, 50000 and 200000. Record
  the resident delta, each overlay's delta and the full-build time against
  the current flag.
- Accept: the resident saving clears the threshold and every overlay stays
  within its cap. Report overlays that grow. If the slowest value wins but
  builds are slow, offer a default value plus a release-only value.

## 4. Generated-code idioms -> shared helper plus one peephole rule

- Detect: census `[frame_idioms]`. SDCC IX epilogues (`ld sp,ix; pop ix;
  ret`) become `jp` to a shared helper. Inline IX prologues in fastcall
  functions become `call` to an HL-preserving helper
  (`ex (sp),ix; push ix; ld ix,2; add ix,sp; ret`).
- Check the census `resident net` figure before proposing a resident helper:
  if occurrences sit mainly in overlays, a resident helper can cost net resident
  bytes even when total storage shrinks.
- Use the project's custom COPT rule file (`-custom-copt-rules`), matching the
  exact text zsdcc emits (`ld	sp, ix` has a space). Export the helper to
  overlays when their rule file uses it.
- Booleanization sequences need flag liveness. Treat them as estimates until a
  rule proves the flags are dead.

## 5. Caller-side stack cleanup -> callee/fastcall ABI

- Detect: census `[abi_cleanup]`, per callee (including `pop`, `inc sp`, and
  SDCC's 5-byte `ld hl,nn; add hl,sp; ld sp,hl` sequence). Convert the largest
  ones: `__z88dk_callee` keeps the C signature; `__z88dk_fastcall` takes one
  argument in registers.
- Single-callsite items (`[1-site: fastcall only]`) cannot win with
  `__z88dk_callee` because moving stack cleanup into the callee cancels the sole
  caller's saving; use `fastcall` or inline instead.
- ASM callees must pop their own arguments, on every exit path. Update ASM
  callers, test drivers and stubs. Guards that pin a dispatcher's decode
  sequence change with it.
- Below the threshold per callee, list only.

## 6. Twin routines -> one implementation plus an adapter

- Detect: census `[mass]` for large ASM. Look for two routines doing the same
  job in different coordinates or ABIs (cell row vs absolute Y, region clear
  vs per-cell clear, unrolled vs loop).
- Accept: output is byte-identical. Prove it with a vector that compares the
  framebuffer or the buffer before and after on the old code first.
- Measure the speed cost with `z88dk-ticks` and report it. A slower hot path
  is a tradeoff for the user, not a free win.

## Then, only when the census or user points there

- `arch`: protocol skeletons, data-driven state machines, buffer lifetimes.
  If repeated state branches dominate, consult only the compact ordered
  state-machine subsection of [playbook H](size-playbook-extended.md#h-control-flow-and-dispatch-density)
  for that `arch` candidate.
- `libpull`: run `libpull_scan.py` only when `[mass]` shows runtime-library
  modules at or above the threshold. If a referenced member pulls unrelated
  routines, check [archive granularity](c-patterns.md#archive-member-extraction-granularity-requiere-build).
- `data`/`compress`: strings, tables and assets, counted net of decoder,
  glue and workspace (`net_compression_check.py`).
- Micro lanes, black-belt and external research run only when the user names
  them: `asm-micro.md`, `size-blackbook.md`, `size-playbook-extended.md`,
  `external-research.md`. Only the targeted `arch` subsection above is exempt;
  it does not open the rest of the extended playbook.

Winners can subsume each other: moving a routine removes its idiom and ABI
counts. Re-run the census after each accepted family.

## Multi-image / banked ROM sets

Measured on a 16K HOME + 8K EXROM interpreter pair (2068-Leap V2, 2026-10); each item paid off
more than the micro passes:

- **Bank-aware accounting.** Report free bytes per image/bank, never a sum across banks; moving a
  routine between banks is a transfer, not a saving, and costs a paging trampoline or slot on the
  calling side. Measure each step with the real build (`make budget`-style report) and keep the
  per-step history; never sum unbuilt candidates.
- **Production-only reachability.** A routine referenced only by legacy or test builds that share a
  source file is dead in the shipped image, but textual scans count those references. Walk the
  label graph of the *shipped listings* with precise fall-through and `EQU` aliases:
  `scripts/production_reachability.py HOME.lst EXROM.lst --roots-below 0x100 --root-prefix
  <slot-name-prefix> --root <dispatch-table>`. Slots placed by address (an `ORG` or `ASSERT` rather
  than a name) must be added as `--root`. Exclude a confirmed routine with a production define,
  not by deleting it (the other builds keep it).
- **Cross-bank slot tables.** Fixed-address jump slots between images accumulate dead slots and
  padding (`ORG`-placed stubs with gaps). Pack the used slots behind computed `EQU`s with an
  `ASSERT` per slot; grep tests and tools for hard-coded slot addresses first.
- **Indirection made redundant by full linking.** A jump table that existed so one image need not
  know the other's addresses is pure cost once the second image is linked against the first's
  symbols; keep only the version/magic check.
- **RST tail calls.** If `rst n` = `call X`, a tail `jp X` becomes `rst n : ret` (-1 byte each);
  only where X does not unwind to a saved SP (see `audit-z80` asm-abi contracts).
- **Dispatch return in IY/IX.** VM handlers ending `jp loop` -> `jp (iy)` (-1 byte, faster) when
  IY is otherwise unused; audit every path that runs foreign code and reload or preserve IY there.
- **Padding reuse.** Small routines can live in RST-slot padding -- **only** if no code falls
  through into them (check the instruction before each one).
- **jp -> jr to a fixed point.** Each pass shortens code and brings more targets into range; repeat
  until no candidate is left.
- **Prove behaviour unchanged for compiler/VM shrinks.** Compile a whole corpus on the old and new
  builds and compare the emitted bytecode byte for byte (and the compile errors); a shrink that
  changes no output needs no new language tests.
