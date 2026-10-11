# ASM And ABI Checks

Prioritize the C to ASM boundary. That is the highest-yield surface for real bugs in these projects.

## Register and stack checks

- Verify every preserved register against the real caller contract, not comments.
- Check every exit path for balanced `push` and `pop`.
- Verify callee-clean vs caller-clean exactly. One extra byte on the stack is enough to crash later.
- Confirm shadow registers are restored before returning to C or mixed callers.
- Verify every flag-dependent branch against the actual preceding instruction. `ld`, `ex`, `push`, `pop`, `di`, and `ei` do not set the flags you may wish they did.
- Trace carry separately. `inc` and `dec` leave carry unchanged, so `jr c/nc` after them is either a deliberate stale-carry trick or a bug.
- Treat `exx`, `ex af,af'`, and `ld sp,...` as whole-routine contracts. One missing restore can corrupt code far away from the local routine.

## Packed-byte traps

- On Z80 SDCC stacks, `uint8_t` arguments are byte-packed, not widened to 16 bits for free.
- A `pop af` shortcut is not a safe way to read a packed trailing byte for a `__z88dk_callee` helper. It consumes two bytes and can read garbage into `A`.
- If you suspect a packed-byte bug, trace the exact stack layout from the call site to the return.

## Boundary audit

For every C to ASM symbol in scope:

- Identify the declaration side: cdecl, `__z88dk_callee`, `__z88dk_fastcall`, `__naked`, other local macros
- Verify parameter order and offsets from the real stack layout
- Verify return register width: `L`, `HL`, or `DEHL`
- Verify preservation of IX and IY against the current preflight profile
- Cross-check exports and imports with `"$SKILL_DIR/scripts/abi_inventory.py"`
- For every inline ASM block in C, list registers written or called helpers and verify the surrounding generated `.asm` keeps C temporaries safe
- For `__z88dk_fastcall`, `__z88dk_callee`, `__smallc`, and `__sdcccall(0/1)`, cite the actual convention used before assigning stack offsets

## ASM-specific hazards

- Relative jump range: prove `jr` is in range instead of assuming
- Intentional fall-through: require evidence, not hope
- `ldir` or `lddr`: check overlap direction, `BC=0`, and post-copy assumptions
- Fixed-address loads or stores: confirm the address contract and aliasing
- Tight loops: count T-states only where timing actually matters
- Stack blitters and push-burst screen writers: verify DI/EI, saved SP, clipping exits, and ISR model before calling them safe
- Screen writers: verify bitmap/attribute address math, row carry, third-screen boundaries, and attribute bleed
- Port I/O: verify register clobbers, contention/timing, and hardware target before trusting a generic emulator result
- `DJNZ` loops containing `CALL`: prove the callee preserves `B` or that the loop counter is saved/restored manually
- `EI; RET/JP/HALT`: treat as an explicit delayed-interrupt contract and verify the following instruction is the intended interrupt boundary
- `pop hl ; jp/jr/call target` or other caller-stack edits: prove every caller is at the same stack depth

## Control-flow state

- Prefer exported/global labels as routine starts. Treat branch-only labels as
  internal until proven otherwise.
- `ret`, `reti`, and `retn` are verified exits. Direct `jp`/`jr` are transfers:
  resolve the target before calling one an internal branch, tail call, or
  non-local exit.
- Do not reset stack, DI/EI, EXX, or alternate-AF state at every label.
- Keep DI state across internal labels until `ei`, a verified return, or a
  proven tail transfer.
- Treat conditional returns/jumps/calls as path hypotheses; a linear scanner
  cannot prove all paths.
- State whether stack and interrupt evidence is path-sensitive or a linear-scan
  approximation.

## Coverage reminder

If you run `full` and read mixed C plus ASM code, do not finalize until you have said something explicit about:

- Register preservation
- Stack cleanup
- Parameter width or packing
- Return-value width
- Relative branches or fall-through in the hot spots you inspected

## Contracts that inserted code breaks silently

Each of these was introduced by a correct-looking change to a working Z80 interpreter ROM and
caught only by a regression suite (2068-Leap V2, 2026-10). Check them for code *being changed*,
not only for code being read:

- **Saved-SP unwinding.** If an error path restores SP from a value saved at a routine's entry
  (`ld sp,(SAVED_SP) : ret`), every routine that can raise must be *called* at the stack depth the
  save expects. Replacing `call X : ret` by a tail `jp X` leaves the unwind slot to be overwritten
  (the unwind then "returns" to a pushed data word).
- **Flag pass-through contracts.** Comments such as "keeps carry" / "flags preserved" on a tail
  `jp` are part of the contract: an inserted `xor a`, `or a`, `and n` or `cp n` breaks it. Prefer
  `ld a,0` / `ld (nn),a` sequences or move the new work to a flag-neutral place.
- **Skip tricks.** `db $FE` (`cp n`) swallows ONE following byte, `db $01`/`$11`/`$21` (`ld rr,nn`)
  swallow TWO: match the skipped instruction's length and the clobbered register.
- **Library status outputs.** A library that reports failure through a status cell (e.g. a
  floating-point calculator's error code) must have that cell checked at every call site that can
  fail; an ignored overflow flag produced silently wrong results.
- **Relocated code and fall-through.** Before moving a routine, check that the instruction before
  it is an unconditional transfer; a fall-through target that moves silently changes control flow.
- **Dispatch registers.** An interpreter that keeps its dispatch address in IY/IX ("handlers end
  `jp (iy)`") loses it in any foreign code -- plug-ins, user machine code, a re-entrant call of the
  interpreter: every such path must preserve or reload it, and the entry must document "destroys IY".
- **Temporaries.** Round-robin temporary slots (strings, floats) must not be reused while an
  earlier result is still referenced on the evaluation stack; nested function results expose it.
- **Persisted images.** Data restored from tape/disk that contains pointers (a saved session, a
  heap) must be validated before it is installed: checksum, an image-identity check (exact code
  build), region boundaries forming one ordered chain, an exact partition of the block, and every
  pointer inside its region. Never follow a stored pointer to check it.

