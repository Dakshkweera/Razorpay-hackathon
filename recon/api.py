"""HTTP surface.

One process serves the API and the built UI, so the finished thing is a single
command and a single URL rather than two servers a reviewer has to reason about.

Raw-input endpoints exist because a reconciliation nobody can audit is worth very
little: the UI lets you read the three source files next to the conclusions drawn
from them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from recon.evaluate.score import attach
from recon.ingest.csvparse import read_bank, read_orders, read_settlements
from recon.llm import resolve_mode
from recon.pipeline import run as run_pipeline
from recon.report import LlmMode, Report

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def create_app(
    data_dir: Path, report_path: Path, seed: int = 42, llm_mode: LlmMode | None = None
) -> FastAPI:
    mode = llm_mode if llm_mode is not None else resolve_mode()
    app = FastAPI(title="Settlement Explainer", version="0.1.0")

    # The Vite dev server proxies /api, so this only matters if someone runs the two
    # halves on different origins by hand.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _load_report() -> Report:
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail="no report yet - run the reconciliation first",
            )
        return Report.model_validate_json(report_path.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "data_dir": str(data_dir),
            "has_report": report_path.exists(),
            "seed": seed,
            "llm_mode": mode.value,
        }

    @app.get("/api/report")
    def get_report() -> Report:
        return _load_report()

    @app.post("/api/run")
    def post_run() -> Report:
        report = run_pipeline(data_dir, seed=seed, llm_mode=mode)
        # Scoring happens strictly after the reconciliation has returned.
        truth_path = data_dir / "truth.json"
        if truth_path.exists():
            attach(report, truth_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8", newline=""
        )
        return report

    @app.get("/api/inputs/{name}")
    def get_inputs(name: str) -> JSONResponse:
        readers = {
            "settlements": (read_settlements, "settlements.csv"),
            "orders": (read_orders, "orders.csv"),
            "bank": (read_bank, "bank.csv"),
        }
        if name not in readers:
            raise HTTPException(status_code=404, detail=f"unknown input file {name!r}")
        reader, filename = readers[name]
        rows, normalise = reader(data_dir / filename)
        return JSONResponse(
            {
                "file": filename,
                "normalise": normalise.model_dump(mode="json"),
                "rows": [row.model_dump(mode="json") for row in rows],
            }
        )

    if WEB_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            candidate = WEB_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app
