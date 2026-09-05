"""Stage 1b - resolving column headers that do not match the canonical schema.

The alias table and the LLM header-mapping tier both exist in
:mod:`recon.ingest.normalise`, but neither was ever exercised by the generated
dataset until the bank statement's own header row was deliberately drifted (see
:data:`recon.generate.writer.BANK_HEADER_OVERRIDES`). These tests are what turn
"there is code for schema drift" into "schema drift was handled, on this run."
"""

from __future__ import annotations

import pytest

from recon.generate.build import build
from recon.generate.writer import write_dataset
from recon.llm.stub import StubProvider
from recon.pipeline import load
from recon.report import MappingMethod


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ingest")
    write_dataset(build(seed=42), directory)
    return directory


def _bank_report(data_dir, provider):
    inputs = load(data_dir, provider=provider)
    return inputs, next(n for n in inputs.normalise if n.file == "bank.csv")


def test_the_bank_header_row_is_actually_drifted(data_dir):
    """Confirms the fixture is real drift, not a claim about drift."""
    header = (data_dir / "bank.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "particulars" in header
    assert "reference_no" in header
    assert "narration" not in header
    assert header.split(",") == ["date", "particulars", "debit", "credit", "balance", "reference_no"]


def test_particulars_resolves_by_alias_with_no_model_at_all(data_dir):
    """The free, deterministic tier: a known synonym needs no provider."""
    inputs, report = _bank_report(data_dir, provider=None)
    mapped = {m.source: m for m in report.columns_mapped}
    assert mapped["particulars"].canonical == "narration"
    assert mapped["particulars"].method is MappingMethod.ALIAS
    assert mapped["particulars"].confidence == 1.0


def test_reference_no_is_unresolved_without_a_model(data_dir):
    """Not every real-world header spelling is in the alias table by design - that gap
    is what the LLM tier exists for. Without one, the honest outcome is a rejected row,
    not a silent guess."""
    inputs, report = _bank_report(data_dir, provider=None)
    mapped = {m.source: m for m in report.columns_mapped}
    assert mapped["reference_no"].canonical == "reference_no"  # never renamed
    assert report.rows_rejected == report.rows_read
    assert len(inputs.bank) == 0


def test_reference_no_resolves_through_the_llm_tier_when_a_model_is_available(data_dir):
    inputs, report = _bank_report(data_dir, provider=StubProvider())
    mapped = {m.source: m for m in report.columns_mapped}
    assert mapped["reference_no"].canonical == "ref"
    assert mapped["reference_no"].method is MappingMethod.LLM
    assert report.rows_rejected == 0
    assert len(inputs.bank) == report.rows_read


def test_every_bank_row_survives_the_drifted_header_with_a_model_present(data_dir):
    inputs, report = _bank_report(data_dir, provider=StubProvider())
    assert len(inputs.bank) == 14
    assert report.rows_rejected == 0
    # The values themselves are untouched by header resolution - only the key changed.
    assert all(row.narration for row in inputs.bank)
    assert all(row.ref for row in inputs.bank)
