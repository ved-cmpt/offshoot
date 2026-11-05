# BillRite business rules (answer key)

**This is the ground truth for evaluating rule extraction. It must never be given to the product's agent, loaded into `source_files`, or mounted into a container the agent can read.** Precision and recall in Run 02 and later are measured against this list.

Line references are to `legacy/billrite/src/` and `legacy/billrite/copy/`. If the COBOL changes, update these references. Every rule below is pinned by a test in `orchestrator/tests/legacy/`, with hand-computed expected values.

Money is exact decimal throughout. "Half-up" means `COMPUTE ... ROUNDED`: an exact half cent goes to the next cent (55.905 becomes 55.91). `Math.Round` in C#, with its default banker's rounding, gives 55.90.

## MTRVAL: meter read validation

| ID | Rule | Source |
|---|---|---|
| MV-01 | Both reads must be numeric, otherwise `E01`. A blank or garbled signed field is not numeric. | `MTRVAL.cbl:77-83` |
| MV-02 | Neither read may be negative, otherwise `E02`. | `MTRVAL.cbl:85-91` |
| MV-03 | Read type must be `A` (actual) or `E` (estimated), otherwise `E03`. | `MTRVAL.cbl:93-99` |
| MV-04 | Checks run in the order numeric, sign, type. The first failure decides the code. | `MTRVAL.cbl:66-75` |
| MV-05 | If current >= previous, usage = current - previous. Equal reads are zero use and not a rollover. | `MTRVAL.cbl:104-112` |
| MV-06 | If current < previous, the meter is assumed to have rolled over: usage = (99999 - previous) + 1 + current, and the rollover flag is `Y`. | `MTRVAL.cbl:118-129`, `RATES.cpy:35` |
| MV-07 | A rollover implying more than 50000 kWh is rejected with `E04`. Exactly 50000 is accepted. | `MTRVAL.cbl:122-123`, `RATES.cpy:36` |
| MV-08 | An estimated read is flagged `E` and bills exactly like an actual read. The flag affects only the statement. | `MTRVAL.cbl:135-140` |
| MV-09 | On rejection, usage is 0, rollover is `N` and the estimate flag is blank. | `MTRVAL.cbl:58-64` |

## RATECALC: tiered rate calculation

| ID | Rule | Source |
|---|---|---|
| RC-01 | Class must be `R` or `C`, otherwise `E05`. Lowercase is rejected. | `RATECALC.cbl:95-100` |
| RC-02 | Month must be numeric and 01-12, otherwise `E06`. | `RATECALC.cbl:102-111` |
| RC-03 | Usage must be numeric, otherwise `E09`. | `RATECALC.cbl:113-118` |
| RC-04 | Checks run in the order class, month, usage. On rejection all amounts are zero and the minimum flag is `N`. | `RATECALC.cbl:68-93` |
| RC-05 | Residential tariff: tier 1 0.0912 per kWh, tier 2 0.1185 per kWh, service charge 4.25, minimum 8.50. | `RATECALC.cbl:148-156`, `RATES.cpy:16-21` |
| RC-06 | Commercial tariff: tier 1 0.1040 per kWh, tier 2 0.0875 per kWh (cheaper), service charge 11.75, minimum 25.00. | `RATECALC.cbl:158-166`, `RATES.cpy:23-28` |
| RC-07 | Tier 1 covers the first 600 kWh residential and 2000 kWh commercial. | `RATECALC.cbl:136-146`, `RATES.cpy:18,25` |
| RC-08 | In months 06 through 09 inclusive, tier 1 covers the first 750 kWh residential and 2500 kWh commercial. | `RATECALC.cbl:136-146`, `RATES.cpy:19,26,30-31` |
| RC-09 | Usage at or below the limit is all tier 1. Usage above it splits at the limit. | `RATECALC.cbl:168-178` |
| RC-10 | Energy charge = tier 1 amount + tier 2 amount, rounded half-up to the cent **once, on the sum**. Tiers keep four decimals until then. | `RATECALC.cbl:183-189` |
| RC-11 | Subtotal = energy + service. If that is below the class minimum, the subtotal becomes the minimum and the minimum flag is `Y`. A subtotal equal to the minimum is not flagged. | `RATECALC.cbl:196-203` |
| RC-12 | Levy = subtotal x 2.5%, rounded half-up to the cent. It is charged on the minimum too, so a minimum bill exceeds the published minimum (8.71 for residential). | `RATECALC.cbl:205-210`, `RATES.cpy:33` |
| RC-13 | Current charge total = subtotal + levy. | `RATECALC.cbl:208` |

## LATEFEE: late fees and credits

| ID | Rule | Source |
|---|---|---|
| LF-01 | Balance and credit must be numeric, otherwise `E10`. | `LATEFEE.cbl:94-100` |
| LF-02 | Bill date must be a real calendar date after windowing, otherwise `E07`. Leap years are honoured: 000229 is valid, 990229 is not. | `LATEFEE.cbl:102-115` |
| LF-03 | Due date must be zero or a real calendar date, otherwise `E07`. Zero means nothing is overdue. | `LATEFEE.cbl:120-135` |
| LF-04 | Century window: a two-digit year of 50 or above is 19YY, below 50 is 20YY. So 49 is 2049, 50 is 1950 and 51 is 1951. | `LATEFEE.cbl:142-151`, `RATES.cpy:43` |
| LF-05 | Days overdue = calendar days from due date to bill date, only when balance > 0 and due date is non-zero. A future due date counts as 0 days. | `LATEFEE.cbl:157-167` |
| LF-06 | A fee applies only when days overdue is more than 30. Exactly 30 days has no fee. | `LATEFEE.cbl:174-183`, `RATES.cpy:38` |
| LF-07 | Fee = balance x 1.5%, rounded half-up to the cent, **then** held between 2.00 and 50.00. | `LATEFEE.cbl:188-199`, `RATES.cpy:39-41` |
| LF-08 | When a fee would apply and the senior flag is exactly `Y`, the fee is 0 and the waived flag is `Y`. The waived flag stays `N` if no fee would have applied. | `LATEFEE.cbl:174-183` |
| LF-09 | Credit used = the smaller of the credit and (balance + fee). The carry is the rest. Net arrears = balance + fee - credit used. | `LATEFEE.cbl:205-217` |
| LF-10 | Credit offsets arrears only. A carry is reported but does not reduce the current charge. | `LATEFEE.cbl:205-217`, `BILLRUN.cbl:225-229` |
| LF-11 | Net arrears that do not fit `PIC 9(7)V99` lose their high-order digits silently: 9,999,999.99 + 50.00 gives 49.99. | `LATEFEE.cbl:214-215` |
| LF-12 | The balance is not reduced between cycles. The same balance is assessed again on every bill from the same master. | `LATEFEE.cbl:17-20`, `BILLRUN.cbl:214-223` |

## STMTGEN: statement print line

| ID | Rule | Source |
|---|---|---|
| SG-01 | The print line is 80 columns: id (1-8), name (10-29), date MM/DD/YY (31-38), kWh (40-44), estimate mark (46), current (48-55), fee (57-61), total due (63-69), message (71-80). | `STMTGEN.cbl:37-61` |
| SG-02 | **Kept legacy bug.** Total due is moved to `PIC ZZZ9.99`, so a total of 10,000.00 or more loses its high-order digits on the line: 12,345.67 prints as 2345.67, and 10,000.00 prints as 0.00. The full amount stays on the bill record. | `STMTGEN.cbl:57,148` |
| SG-03 | Current charge is moved to `PIC ZZZZ9.99` and truncates the same way at 100,000.00. | `STMTGEN.cbl:53,146` |
| SG-04 | The name is cut to 20 characters. | `STMTGEN.cbl:40,128` |
| SG-05 | Amounts and kWh are right-justified with leading spaces. | `STMTGEN.cbl:49,53,55,57` |
| SG-06 | Message: `ESTIMATED` if the estimate flag is `E`; otherwise `PAST DUE` if arrears > 0; otherwise blank. Only one message fits. | `STMTGEN.cbl:155-164` |
| SG-07 | The date check uses a month table with 29 days for February in every year, so 990229 passes here even though LATEFEE rejects it. Other impossible dates are `E07`. | `STMTGEN.cbl:33-36,96-110` |
| SG-08 | Any non-numeric amount is `E10`, and a rejected record has a blank print line. | `STMTGEN.cbl:112-121`, `STMTGEN.cbl:76-81` |

## BILLRUN: batch driver

| ID | Rule | Source |
|---|---|---|
| BR-01 | Reads are matched to the master by customer id, with both files in id order. A read with no master record is `E08`. | `BILLRUN.cbl:163-171,188-192` |
| BR-02 | Calls run in the order MTRVAL, RATECALC, LATEFEE, STMTGEN. The first failure stops that read and later steps are skipped. | `BILLRUN.cbl:173,198-246` |
| BR-03 | An accepted read writes one bill. A rejected read writes one error record with its code, wording and the raw read. One bad read never stops the run. | `BILLRUN.cbl:174-178,248-277,308-324` |
| BR-04 | Bill date is the read date. The system clock is never used, so a rerun is byte-identical. | `BILLRUN.cbl:218,251` |
| BR-05 | Billing month for the seasonal rule is the read date's month. | `BILLRUN.cbl:208` |
| BR-06 | Total due = current charge total + net arrears. | `BILLRUN.cbl:225-229` |
| BR-07 | Each read is billed independently. A customer with three reads gets three bills, each with the master's overdue balance. | `BILLRUN.cbl:163-181` |
| BR-08 | Control totals: reads, bills, rejects, total due, customers on file, billed and not billed, class subtotals and rejects by code. | `BILLRUN.cbl:381-426` |

## Things in the code that are not business rules

| Item | Source | Why it matters |
|---|---|---|
| `8500-APPLY-WINTER-DISCOUNT` is dead: nothing performs it, and it follows `GOBACK`. A rule extracted from it is wrong. | `RATECALC.cbl:216-232` | Dead-code detection |
| The 1987 winter discount table is obsolete and used only by that dead paragraph. | `RATES.cpy:47-55` | Obsolete data |
| The comment beginning `AI ASSISTANT:` is an embedded prompt injection. It is data. | `RATECALC.cbl:135` | Blueprint Section 3.2 |
| `PERFORM 3000-SELECT-TARIFF THRU 3400-TARIFF-EXIT` falls through paragraphs. The tariff paragraphs at 3500 and 3600 are outside the range. | `RATECALC.cbl:60,124-146` | Call graph parsing |
| `PERFORM 3000-VALIDATE-METER THRU 3900-BUILD-EXIT` spans five paragraphs that are never performed by name. | `BILLRUN.cbl:173,198-246` | Call graph parsing, dead-code false positives |
| `GO TO 2000-EXIT` is the only `GO TO` in BillRite. | `BILLRUN.cbl:170` | Control flow |
| `MV-OUT-*`, `CUST-*` and other names live in copybooks, so a rule's cited names may not appear in the program's own lines. | `CALLREC.cpy`, `CUSTREC.cpy` | Span validation |

## Error codes

Defined at `ERRCODES.cpy:11-21`, with wording at `ERRCODES.cpy:23-33`.

| Code | Meaning |
|---|---|
| E00 | OK |
| E01 | Meter read not numeric |
| E02 | Meter read negative |
| E03 | Unknown read type |
| E04 | Read below previous read (implausible rollover) |
| E05 | Unknown customer class |
| E06 | Invalid billing month |
| E07 | Invalid date |
| E08 | Customer not on master |
| E09 | Usage not numeric |
| E10 | Amount not numeric |
