"""The LLM layer: the cache, the stub, and the two places they plug into the pipeline.

None of this suite calls a real model. ``StubProvider`` is deterministic and offline,
which is exactly what makes it possible to assert on its behaviour at all - a real
model's answer to the same prompt is not something a test can pin down.
"""

from __future__ import annotations

import json

import pytest

from recon.classify.residue import RESIDUE_CONFIDENCE_THRESHOLD, apply as apply_residue
from recon.ingest.normalise import resolve_headers
from recon.llm.base import LlmError
from recon.llm.cache import CachingProvider, cache_key
from recon.llm.stub import StubProvider
from recon.narration.cache import NarrationCache
from recon.narration.extract import extract_all, extract_all_llm
from recon.model import BankRow
from recon.money import Paise
from recon.report import (
    Attempt,
    BatchReport,
    ComponentKind,
    ComponentSource,
    ExceptionKind,
    ExceptionReport,
    GapComponent,
)


def _bank_row(ref: str, narration: str, credit: int = 100) -> BankRow:
    from datetime import date

    return BankRow(date=date(2026, 8, 3), narration=narration, credit=Paise(credit), ref=ref)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

def test_cache_key_is_stable_and_schema_scoped():
    a = cache_key(schema_name="x", system="s", user="u")
    b = cache_key(schema_name="x", system="s", user="u")
    c = cache_key(schema_name="y", system="s", user="u")
    assert a == b
    assert a != c


class _CountingProvider:
    name = "counting"

    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.calls = 0

    def complete_json(self, *, schema_name, schema, system, user):
        self.calls += 1
        return self.answer


def test_caching_provider_replays_without_calling_inner(tmp_path):
    inner = _CountingProvider({"ok": True})
    cached = CachingProvider(inner, tmp_path)

    first = cached.complete_json(schema_name="s", schema={}, system="sys", user="u1")
    second = cached.complete_json(schema_name="s", schema={}, system="sys", user="u1")

    assert first == second == {"ok": True}
    assert inner.calls == 1  # the second call was a cache hit, not a re-call
    assert cached.calls == 2
    assert cached.cache_hits == 1


def test_read_only_caching_provider_never_writes_a_fixture(tmp_path):
    cached = CachingProvider(StubProvider(), tmp_path, read_only=True)
    cached.complete_json(
        schema_name="residue_classification_v1",
        schema={},
        system="s",
        user=json.dumps({"residual_paise": 100, "tried": []}),
    )
    assert list(tmp_path.glob("*.json")) == []


# --------------------------------------------------------------------------- #
# Stub provider
# --------------------------------------------------------------------------- #

def test_stub_refuses_a_schema_it_does_not_know():
    with pytest.raises(LlmError):
        StubProvider().complete_json(schema_name="nonsense", schema={}, system="", user="{}")


def test_stub_residue_classification_is_conservative():
    provider = StubProvider()
    response = provider.complete_json(
        schema_name="residue_classification_v1",
        schema={},
        system="",
        user=json.dumps({"residual_paise": 180000, "tried": [{"check": "x", "outcome": "y"}]}),
    )
    assert response["confidence"] < RESIDUE_CONFIDENCE_THRESHOLD


# --------------------------------------------------------------------------- #
# Narration: the LLM may only add what the regex missed, and only when honest
# --------------------------------------------------------------------------- #

def test_llm_pass_does_not_recover_a_truncated_reference(tmp_path):
    """The generator's ``_garble`` replaces the tail with literal '####' - genuinely
    gone, not merely obfuscated. No honest model, stub or real, can recover it."""
    rows = [_bank_row("N0001", "NEFT-RZPY-4O29I433#### STTL/CR")]
    merged = extract_all_llm(rows, StubProvider(), NarrationCache(tmp_path / "cache.json"))
    assert merged["N0001"].all_utrs == ()


def test_llm_pass_does_not_invent_a_reference_where_none_exists(tmp_path):
    rows = [_bank_row("N0001", "NEFT CR RAZORPAY SOFTWARE PVT LTD SETTLEMENT")]
    merged = extract_all_llm(rows, StubProvider(), NarrationCache(tmp_path / "cache.json"))
    assert merged["N0001"].all_utrs == ()


def test_llm_pass_never_weakens_what_the_regex_already_read(tmp_path):
    rows = [_bank_row("N0001", "NEFT-RAZORPAY SOFTWARE PVT-UTR402913847562-SETTLEMENT")]
    base = extract_all(rows)
    merged = extract_all_llm(rows, StubProvider(), NarrationCache(tmp_path / "cache.json"))
    assert merged["N0001"].utrs == base["N0001"].utrs
    assert merged["N0001"].confidence >= base["N0001"].confidence


def test_no_provider_leaves_narrations_at_the_regex_floor():
    rows = [_bank_row("N0001", "NEFT CR RAZORPAY SOFTWARE PVT LTD SETTLEMENT")]
    assert extract_all_llm(rows, None) == extract_all(rows)


def test_narration_cache_is_reused_across_calls(tmp_path):
    """A second batch containing an already-cached narration must not re-call the model."""
    cache_path = tmp_path / "cache.json"
    narration = "NEFT CR RAZORPAY SOFTWARE PVT LTD SETTLEMENT"

    class _EchoingProvider(_CountingProvider):
        def complete_json(self, *, schema_name, schema, system, user):
            self.calls += 1
            keys = [item["key"] for item in json.loads(user)["narrations"]]
            return {
                "results": [
                    {"key": key, "utr": None, "counterparty": None, "kind": "unknown", "confidence": 0.2}
                    for key in keys
                ]
            }

    provider = _EchoingProvider({})
    rows = [_bank_row("N0001", narration)]
    extract_all_llm(rows, provider, NarrationCache(cache_path))
    extract_all_llm(rows, provider, NarrationCache(cache_path))
    # Two independent NarrationCache instances load from the same file, so the second
    # pass should find its one narration already resolved.
    assert provider.calls == 1


# --------------------------------------------------------------------------- #
# Residue classification: never invents, never changes the amount
# --------------------------------------------------------------------------- #

def _residual_batch(residual: int) -> BatchReport:
    from datetime import date, datetime, timezone

    batch = BatchReport(
        settlement_id="setl_TEST",
        utr="000000000000",
        settled_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 1),
        bank_credit=Paise(1000),
        headline_gap=Paise(residual),
        residual=Paise(residual),
        components=[
            GapComponent(
                kind=ComponentKind.UNEXPLAINED,
                amount=Paise(residual),
                source=ComponentSource.DETERMINISTIC,
                check="residual",
                detail="no deterministic check accounts for this",
                attributed=False,
            )
        ],
    )
    return batch


def _residual_exception(batch: BatchReport) -> ExceptionReport:
    return ExceptionReport(
        id="EXC-01",
        kind=ExceptionKind.UNEXPLAINED_RESIDUE,
        amount=batch.residual,
        settlement_id=batch.settlement_id,
        what="residual gap",
        tried=[Attempt(check="fee recompute", outcome="matched contract")],
    )


def test_residue_classification_never_changes_the_amount():
    batch = _residual_batch(180000)
    exception = _residual_exception(batch)
    apply_residue([batch], [exception], StubProvider())

    assert int(batch.residual) == 180000  # untouched - only decompose may set this
    component = next(c for c in batch.components if c.kind is ComponentKind.UNEXPLAINED)
    assert int(component.amount) == 180000


def test_residue_classification_below_threshold_stays_unattributed():
    batch = _residual_batch(180000)
    exception = _residual_exception(batch)
    apply_residue([batch], [exception], StubProvider())

    component = next(c for c in batch.components if c.kind is ComponentKind.UNEXPLAINED)
    assert component.confidence < RESIDUE_CONFIDENCE_THRESHOLD
    assert component.attributed is False
    assert component.source is ComponentSource.LLM
    assert exception.threshold == RESIDUE_CONFIDENCE_THRESHOLD


def test_residue_classification_is_skipped_entirely_when_llm_is_off():
    batch = _residual_batch(180000)
    exception = _residual_exception(batch)
    apply_residue([batch], [exception], None)

    component = next(c for c in batch.components if c.kind is ComponentKind.UNEXPLAINED)
    assert component.source is ComponentSource.DETERMINISTIC
    assert component.confidence is None


def test_residue_classification_skips_batches_with_nothing_left():
    batch = _residual_batch(0)
    batch.components = []
    apply_residue([batch], [], StubProvider())
    assert batch.components == []


# --------------------------------------------------------------------------- #
# Header mapping
# --------------------------------------------------------------------------- #

CANONICAL = ["settlement_id", "payment_id", "amount", "utr"]


def test_exact_headers_need_no_alias_or_llm():
    resolved, mappings = resolve_headers(CANONICAL, CANONICAL, provider=None)
    assert resolved == {name: name for name in CANONICAL}
    assert all(m.method.value == "exact" for m in mappings)


def test_known_alias_resolves_without_a_provider():
    resolved, mappings = resolve_headers(["txn_id", "amount"], CANONICAL, provider=None)
    assert resolved["txn_id"] == "payment_id"
    aliased = next(m for m in mappings if m.source == "txn_id")
    assert aliased.method.value == "alias"


def test_unknown_header_falls_through_to_the_llm():
    resolved, mappings = resolve_headers(["mystery_column"], CANONICAL, provider=StubProvider())
    mapping = next(m for m in mappings if m.source == "mystery_column")
    assert mapping.method.value == "llm"


def test_unknown_header_without_a_provider_is_left_unmapped():
    resolved, mappings = resolve_headers(["mystery_column"], CANONICAL, provider=None)
    assert "mystery_column" not in resolved
