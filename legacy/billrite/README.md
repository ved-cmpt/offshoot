# BillRite

An original, synthetic 1990s-style utility billing batch system for the fictional Town of Northgate. It exists so that LegacyLens has a legacy application to modernize. All code, names and data are invented.

## Layout

```text
src/       The five programs: BILLRUN, MTRVAL, RATECALC, LATEFEE, STMTGEN
copy/      Copybooks: CUSTREC, READREC, BILLREC, RATES, ERRCODES, CALLREC
data/      CUSTFILE.dat, READFILE.dat, LAYOUTS.txt
harness/   BRCALL, the per-record entry point. Test tooling, not part of BillRite.
Makefile   Build and batch run. Runs inside cobol-runner.
```

## Run the batch

```powershell
docker compose run --rm cobol-runner make billrun
```

This compiles the programs, runs them with networking disabled, and writes `BILLFILE.dat` and `ERRFILE.dat` to `legacy/billrite/out/` (git-ignored). The run log prints control totals.

The line `Warning: program compiled against libxml 212 using older 209` comes from Debian's GnuCOBOL package and is harmless.

## Regenerate the data

The data is seeded and deterministic, so this reproduces the committed files byte for byte:

```powershell
python scripts/generate_billrite_data.py
```

## Call one module per record: BRCALL

```text
BRCALL MTRVAL|RATECALC|LATEFEE|STMTGEN
```

Each line on stdin is one input record. Each input line produces exactly one line on stdout. A record the module rejects is still a normal output record with a status code; the exit code stays 0. Exit code 2 means an unknown module name, and 3 a failed stdin read.

```powershell
docker compose exec cobol-runner sh -c "echo R0100610 | nonet /work/build/BRCALL RATECALC"
```

The layouts below match `copy/CALLREC.cpy`, which holds the same bytes the programs use. `9(n)V99` is zero-filled digits with an implied decimal point. `S9(5)` has a leading separate sign. The status is `E00` when accepted.

### MTRVAL

| Input (13 bytes) | Picture | | Output (10 bytes) | Picture |
|---|---|---|---|---|
| previous read | S9(5) | | status | X(3) |
| current read | S9(5) | | kWh used | 9(5) |
| read type `A`/`E` | X(1) | | rollover `Y`/`N` | X(1) |
| | | | estimate flag `E`/blank | X(1) |

Example: `+99950+00100A` gives `E0000150Y` followed by one blank (the estimate flag).

### RATECALC

| Input (8 bytes) | Picture | | Output (58 bytes) | Picture |
|---|---|---|---|---|
| class `R`/`C` | X(1) | | status | X(3) |
| month | 9(2) | | tier limit | 9(5) |
| kWh | 9(5) | | tier 1 kWh | 9(5) |
| | | | tier 2 kWh | 9(5) |
| | | | energy charge | 9(7)V99 |
| | | | service charge | 9(3)V99 |
| | | | subtotal | 9(7)V99 |
| | | | minimum applied `Y`/`N` | X(1) |
| | | | levy | 9(5)V99 |
| | | | total | 9(7)V99 |

### LATEFEE

| Input (29 bytes) | Picture | | Output (37 bytes) | Picture |
|---|---|---|---|---|
| overdue balance | 9(7)V99 | | status | X(3) |
| due date YYMMDD | 9(6) | | days overdue | 9(5) |
| bill date YYMMDD | 9(6) | | late fee | 9(3)V99 |
| senior flag | X(1) | | waived `Y`/`N` | X(1) |
| credit | 9(5)V99 | | credit used | 9(5)V99 |
| | | | credit carried | 9(5)V99 |
| | | | net arrears | 9(7)V99 |

### STMTGEN

| Input (82 bytes) | Picture | | Output (83 bytes) | Picture |
|---|---|---|---|---|
| customer id | X(8) | | status | X(3) |
| name | X(30) | | print line | X(80) |
| bill date YYMMDD | 9(6) | | | |
| kWh | 9(5) | | | |
| estimate flag | X(1) | | | |
| current charge | 9(7)V99 | | | |
| late fee | 9(3)V99 | | | |
| net arrears | 9(7)V99 | | | |
| total due | 9(7)V99 | | | |

## File layouts

`data/LAYOUTS.txt` documents the input files. The output layouts are `copy/BILLREC.cpy` (190 bytes) and the `ERROR-RECORD` in `src/BILLRUN.cbl` (87 bytes).
