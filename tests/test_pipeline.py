"""The pipeline must read back exactly what the generator wrote, and agree with itself.

These tests deliberately compare the reconciler's own arithmetic against the planted
truth. That is legitimate here — the *test* may read truth.json, the pipeline may not.
"""

from __future__ import annotations

import pytest

from recon.generate.build import build
from recon.generate.writer import write_dataset
from recon.llm.stub import StubProvider
from recon.pipeline import assemble_batches, load, run
from recon.report import LlmMode
from recon.truth import Truth


def _run(data_dir):
    # Explicit and offline: hermetic regardless of what the ambient repo's
    # fixtures/llm/ happens to contain.
    return run(data_dir, llm_mode=LlmMode.STUB)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("data")
    write_dataset(build(seed=42), directory)
    return directory


@pytest.fixture(scope="module")
def truth(data_dir) -> Truth:
    return Truth.model_validate_json((data_dir / "truth.json").read_text(encoding="utf-8"))


def test_every_row_survives_the_round_trip(data_dir, truth):
    inputs = load(data_dir, provider=StubProvider())
    assert len(inputs.settlements) == truth.settlement_rows
    assert len(inputs.orders) == truth.order_rows
    assert len(inputs.bank) == truth.bank_rows
    assert all(report.rows_rejected == 0 for report in inputs.normalise)


def test_batch_totals_agree_with_the_planted_truth(data_dir, truth):
    computed = {batch.settlement_id: batch for batch in assemble_batches(load(data_dir, provider=StubProvider()))}
    assert set(computed) == {batch.settlement_id for batch in truth.batches}

    for planted in truth.batches:
        actual = computed[planted.settlement_id]
        assert int(actual.gross_settled) == int(planted.gross_settled)
        assert int(actual.total_fee) == int(planted.total_fee)
        assert int(actual.total_tax) == int(planted.total_tax)
        assert int(actual.orders_expected) == int(planted.orders_expected)


def test_inferred_windows_match_the_windows_the_generator_used(data_dir, truth):
    computed = {batch.settlement_id: batch for batch in assemble_batches(load(data_dir, provider=StubProvider()))}
    for planted in truth.batches:
        actual = computed[planted.settlement_id]
        assert actual.window_start >= planted.window_start
        assert actual.window_end <= planted.window_end


def test_the_report_is_stable_across_runs(data_dir):
    first, second = _run(data_dir), _run(data_dir)
    assert first.meta.deterministic_hash == second.meta.deterministic_hash
    assert first.meta.deterministic_hash != ""


def test_wall_clock_is_excluded_from_the_hash(data_dir):
    report = _run(data_dir)
    original = report.meta.deterministic_hash
    report.meta.runtime_ms += 999
    report.scoreboard.runtime_ms += 999

    from recon.pipeline import deterministic_hash

    assert deterministic_hash(report) == original


def test_the_pipeline_never_reads_the_truth_file(data_dir):
    """The whole scoreboard is worthless if the reconciler can see the answers."""
    hidden = data_dir / "truth.json"
    contents = hidden.read_text(encoding="utf-8")
    hidden.unlink()
    try:
        report = _run(data_dir)
        assert report.scoreboard.settlement_batches > 0
    finally:
        hidden.write_text(contents, encoding="utf-8", newline="")
