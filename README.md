# Settlement Explainer

**Razorpay Buildathon 2026 · Track 04: AI Finance Controller**

A merchant's dashboard says a settlement went out. The bank says a different number
arrived. The difference is fees, GST on fees, refunds that crossed a cycle boundary,
adjustments — and occasionally something genuinely wrong. Finding out which is which
is done by hand, in a spreadsheet, monthly, by someone who cannot tell an expected
timing difference from money worth querying without tracing individual transactions
across three files whose identifiers don't line up.

This closes that loop: normalise three inconsistent schemas, match what can be
matched, decompose what's left, and produce a defensible statement of what is
explained and what isn't.

```
Records processed          545   (275 settlement, 256 order, 14 bank)
Settlement batches           9
Runtime                    19ms

Matched deterministically    6   (66.7%)
Matched by inference         0   ( 0.0%)
Unmatched exceptions         3   (33.3%)

Gap explained       ₹13,390.67   (88.2%)
Gap unexplained      ₹1,800.00   (11.8%)

FALSE MATCHES                0
FALSE CAUSE ATTRIBUTIONS     0
```

The two zeros are the point. **In reconciliation a wrong match is worse than an
honest gap, because it silently closes the books on a real problem.** The match rate
is deliberately under 100%, and the unexplained figure is exactly the amount planted
as unexplainable — not approximately, exactly.

---

## Quickstart

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
```

```bash
.venv/Scripts/python -m recon.cli generate   # write the dataset and its hidden truth
```

```bash
.venv/Scripts/python -m recon.cli run        # reconcile, score, write out/report.json
```

```bash
.venv/Scripts/python -m recon.cli verify     # prove the data and the run reproduce
```

For the UI — one process serves the API and the built page:

```bash
pnpm --dir web install && pnpm --dir web build && .venv/Scripts/python -m recon.cli serve
```

No API key is needed for any of the above. Nothing reaches the network unless you
ask it to.

---

## Why the accuracy figures mean anything

Most reconciliation demos show a match and assert it was right. This one plants the
answers first.

`recon generate` writes the three CSVs **and** a `data/truth.json` recording every
defect it planted and its exact value in paise. The reconciler never reads that file
— `recon/evaluate/` does, after the pipeline has returned a finished report. There is
a test asserting the pipeline still runs with `truth.json` deleted, because the moment
the reconciler can see the answers, every number on the scoreboard becomes worthless.

So `FALSE MATCHES: 0` is not a claim that nothing looked wrong. It means every
committed match was checked against the bank line the generator actually paid, and
none was wrong.

### The ten planted cases

All ten pass. Cases 6 and 10 are the ones that matter: they are where the correct
behaviour is to refuse.

| # | Case | Required output |
|---|---|---|
| 1 | Clean batch, UTR matches | matched by R1, residual 0 |
| 2 | Fees and GST only | fully decomposed, residual 0 |
| 3 | Refund settled in the next cycle | found by adjacent-cycle search, both ends resolved |
| 4 | Fee charged at 1.2% against a contracted 0.8% | flagged as rate drift |
| 5 | Garbled narration, UTR unreadable | matched on amount within ±2 days, lower confidence |
| 6 | Two batches, identical amount, same day | **ambiguous → exception, not a guess** |
| 7 | Duplicate UTR across two bank lines | flagged, not double-counted |
| 8 | Bank credit with no settlement at all | exception |
| 9 | Settlement with no bank credit | exception, timing noted as an inference |
| 10 | Genuinely unexplainable ₹1,800 | **exception, no invented cause** |

---

## Design principle

**Deterministic where money is concerned. AI only where the input is unstructured.**

| Task | Handled by | Why |
|---|---|---|
| Matching by exact identifier | Python | Exact, verifiable, reproducible |
| Fee recomputation, all arithmetic | Python | Never let a model do arithmetic on money |
| Reading bank narration strings | LLM | Genuinely unstructured, varies per bank |
| Classifying an unexplained residue | LLM | Requires reasoning over context |
| Committing a match | Python + threshold | The model proposes; the engine disposes |

Money is `int` paise throughout. Python's integers are arbitrary precision, so
addition and subtraction cannot drift, and the single operation that could leave
integer space — applying a rate — goes through one function in
[`recon/money.py`](recon/money.py) that multiplies before dividing and states its
rounding rule. There is exactly one rounding site in the system.

Two thresholds govern every commitment: **0.85** to commit a match, **0.70** to
attribute a cause. Below either, the answer is an exception.

### How the gap decomposes

The gap explained is `orders_expected − bank_credit` — what the merchant's own
records say they earned against what actually arrived. It decomposes exactly:

```
headline_gap = fee + gst + unlinked_adjustments + settlement_residual
```

The first three are deductions the order book never knew about, recomputable from
the settlement file and the contract. The fourth is the interesting one: money the
settlement file itself says should have arrived and did not. Five deterministic
checks run against it — fee recompute, GST verification, adjacent-cycle refund
search, unlinked adjustments, and a bounded rounding check — and whatever survives
is reported as unexplained.

Rounding is *bounded*, not assumed: at most one paise per payment plus 99 paise of
whole-rupee payout truncation. That bound is what lets the system rule rounding
**out** on batches where it cannot reach, which is how the ₹1,800 residue survives
to be reported honestly.

---

## Reproducibility

Two claims, both checked by `recon verify`:

- The three CSVs regenerate **byte-identical** from seed 42.
- Two runs of the pipeline produce the same `deterministic_hash`.

Wall-clock fields are excluded from that hash, because runtime is a property of the
machine and not of the reconciliation. A `.gitattributes` pins LF endings, so the
first claim holds on a fresh clone regardless of platform.

---

## Architecture

```
recon/money.py         Paise, and the only rounding site in the system
recon/model.py         typed records for the three input files
recon/report.py        THE CONTRACT — every model the UI is typed from
recon/truth.py         planted ground truth (read only by recon/evaluate)
recon/generate/        synthetic data + truth.json, seeded and declarative
recon/ingest/          CSV parsing and schema normalisation
recon/narration/       reading identifiers off bank narrations
recon/match/           R1–R4, ambiguity and duplicate handling
recon/decompose/       the five deterministic gap checks
recon/classify/        LLM residue classification at the 0.70 threshold
recon/evaluate/        scoring against truth.json
recon/llm/             provider interface, Perplexity client, stub, fixture cache
web/                   React + Vite UI, typed from the generated schema
```

Engine and UI share one contract. Pydantic models emit
[`schema/report.schema.json`](schema/report.schema.json), which generates
`web/src/types/report.d.ts`. Rename a field in Python and the frontend fails to
compile, rather than rendering `undefined` during a demo.

```bash
.venv/Scripts/python -m recon.cli schema && pnpm --dir web types
```

---

## The LLM layer

Every caller takes an `LlmProvider | None` and asks nothing about which one it is.
[`recon/llm/__init__.py`](recon/llm/__init__.py) is the only file that knows
Perplexity exists; adding another provider means one new file and one branch.

Four modes, resolved cheapest-and-most-offline first:

| Mode | Behaviour |
|---|---|
| `off` | no provider; every caller falls back to its deterministic floor |
| `stub` | deterministic offline stand-in, always available, never touches the network |
| `cache` | replay committed fixtures; a miss degrades to the stub rather than failing |
| `live` | call Perplexity, writing each response as a new fixture |

Without a key and without `RECON_LLM_MODE`, a run uses `cache` if fixtures exist,
otherwise `stub`. Never an error, never a network call nobody asked for. Override
per run with `--llm live` or `RECON_LLM_MODE`.

Live mode uses `sonar` with `disable_search: true`, `response_format: json_schema`
and `temperature: 0` — structured extraction with no web grounding, which is what
narration parsing actually needs.

Copy `.env.example` to `.env` and fill in the key — the CLI loads it at startup, and
values already exported in your shell win.

```bash
.venv/Scripts/python -m recon.cli run --llm live
```

The endpoint is configurable, because "a Perplexity key" and "an OpenRouter key" are
different things and sending one to the other's API earns a 401. Leave
`PERPLEXITY_BASE_URL` unset for Perplexity direct (`pplx-` keys); point it at
`https://openrouter.ai/api/v1` with `PERPLEXITY_MODEL=perplexity/sonar` for an
OpenRouter key (`sk-or-`).

A live run that cannot reach the model does **not** quietly succeed. Every caller falls
back to its deterministic floor so a demo never crashes, but the failure is counted and
the scoreboard says so:

```
LLM   perplexity/live   calls 1   cache hits 0   errors 1

!! LLM DEGRADED: 1 call failed and fell back to the deterministic stub.
   perplexity request failed: Client error '401 Unauthorized' ...
   Results below came from rules, not from the model.
```

### The model proposes, the engine disposes

Asked to classify the ₹1,800 residue, Sonar proposed **`unlinked_adjustment` at 0.96
confidence** — reasoning, circularly, that because an unlinked adjustment had been found
on that batch, the remainder must be one too. That is exactly the failure this project
exists to prevent, and a confidence threshold alone would have let it straight through.

So a proposed cause is checked against what the deterministic pass already established.
The unlinked-adjustment check had already run and attributed ₹1,676; the residue is by
definition what that check *could not* account for, so the same cause cannot explain it
again. The proposal is refuted, the money stays unexplained, and the exception records
the refusal:

```
The classifier proposed "unlinked_adjustment" at confidence 0.96, but the engine
refuted it: the unlinked_adjustment check already ran and attributed ₹1,676.00;
this residue is what it could not account for, so the same cause cannot explain
it again. The amount stays unexplained.
```

---

## Known limitations

Stated here rather than discovered by a reviewer:

- **`Matched by inference` is currently 0.** The LLM's identifier-recovery path is
  implemented but never fires on this dataset. The garbled narration masks four
  digits of the UTR, so even perfect lookalike-glyph repair (`4O29I433####` →
  `40291433####`) leaves eight digits — below the nine-digit reference floor and
  short of a full UTR. The AI's measurable contribution to *matching* is therefore
  zero, and the scoreboard says so rather than rounding it up.
- The committed fixtures are now genuine model output, captured from a live run. The
  demo replays them offline in `cache` mode and reproduces the live figures exactly.
- Ten planted cases is a floor, not a ceiling. Chargebacks, partial settlements,
  multi-currency and TDS are all out of scope for this loop.

---

## Tests

```bash
.venv/Scripts/python -m pytest
```

88 tests. One per planted case, the decomposition identity asserted exactly
(components plus residual must equal the gap to the paise), determinism at both the
data and report level, and a test that the pipeline still runs with `truth.json`
deleted.
