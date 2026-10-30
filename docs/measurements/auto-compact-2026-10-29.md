# Auto-compact window of main sessions: the calculation of 2026-10-29

For people. Agents read only the decision: `skills/orchestration/references/routing.md` (last line).
Decision: `CLAUDE_CODE_AUTO_COMPACT_WINDOW` = 400000 (was 700000), on the operator's word of 2026-10-29 (the calculation below first led to 250000).

## Turn price of a main session (Opus 5.5, warm cache)

`turn = C × 0.20/1e6 (cache read) + 0.028 (new input + output, measured)`

| Context C | read | warm turn | cold (5m write, ×5) | cold (1h write, ×8) |
|---|---|---|---|---|
| 100k | $0.020 | $0.048 | $0.50 | $0.80 |
| 290k | $0.058 | $0.086 | $1.45 | $2.32 |
| 500k | $0.100 | $0.128 | $2.50 | $4.00 |

Check: the model gives $0.086 per turn at 290k, measured $0.091 — within 6 %. One cache miss at 290k (1h write) ≈ 40 warm turns.

## Price of a compaction cycle

Assumptions [A]: base after compaction b = 50k; summary 15k output tokens; "forgotten, re-read" penalty $0.25.
Measured: context growth per turn g = 2.4k (1.7k write + 0.7k output).

One compaction at window W, warm: `W × 0.20/1e6 + 15k × 20/1e6 + 15k × 8/1e6 + 0.25` ≈ $0.74–0.78.

Mean turn price over a cycle `50k → W`: turns per cycle = (W − 50k) / 2.4k; mean context = (W + 50k) / 2;
turn = 0.028 + mean context × 0.20/1e6 + compaction price / turns.

| W | turns per cycle | mean context | turn price |
|---|---|---|---|
| 150k | 42 | 100k | $0.065 |
| 200k | 62 | 125k | $0.0645 |
| 250k | 83 | 150k | $0.067 |
| 300k | 104 | 175k | $0.070 |
| 400k | 146 | 225k | $0.078 |
| 500k | 188 | 275k | $0.087 |
| 700k | 271 | 375k | $0.106 |

The minimum is flat between 150k and 250k; 250k keeps the longest cycle in that band. At W = 500k the model gives a mean
context of 275k against the measured 288–318k, so the model is plausible. 500k → 250k: −23 % per turn, ≈ $15–22 per
$97 of main-session spend. Only money is counted; quality loss from compaction is not measured.
At the chosen 400k, by the same model: $0.078 per turn — +16 % against 250k ($0.067), −10 % against 500k ($0.087).

Source: the research report `model-routing.md` §5 (observer's scratchpad, 2026-10-29); prices — platform.claude.com.
