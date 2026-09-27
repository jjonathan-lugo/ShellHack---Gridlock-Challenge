"""Autonomous re-computation: watch the data and rebuild whatever it feeds.

    python3 -m backend.ingest.watch            # poll every 3 s until Ctrl+C
    python3 -m backend.ingest.watch --once     # one pass: rebuild anything stale, then exit

  Projects_Overlaps.xlsx changed  -> re-export projects.json, recompute
                                     overlaps.json, note any disagreement with
                                     the sheet's own overlaps tab
  a source PDF changed            -> re-run the PDF -> geocode -> overlap pipeline
                                     (data/processed/auto/)
  new projects appeared           -> fetch weather history for just those

Standard library only (plus openpyxl/pdfplumber for the steps that need them).
The browser picks up the new JSON on its next refresh; the backend's
/overlaps endpoint already recomputes on every request.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from backend.ingest.xlsx_export import PROCESSED, XLSX, export_and_recompute

REPO_ROOT = Path(__file__).resolve().parents[2]
PDFS = [
    REPO_ROOT / "data" / "Dominion Engery" / "2024-2028-2million-and-above-project-descriptions.pdf",
    REPO_ROOT / "data" / "Georgia Power" / "2025 IRP Volume 3 PUBLIC DISCLOSURE.pdf",
]
STATE_FILE = REPO_ROOT / "data" / "cache" / "watch_state.json"


def _mtimes(paths: list[Path]) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in paths if p.exists()}


def refresh_weather(projects_path: Path, cache_path: Path, log=print) -> int:
    """Fetch weather for projects missing from the cache. Returns how many were added."""
    from backend.weather.fetch import build_climatology_cache

    projects = json.loads(projects_path.read_text())
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else None
    have = set(cache["projects"]) if cache else set()
    missing = [p for p in projects if p.get("lat_center") is not None and p["project_id"] not in have]
    if not missing:
        return 0
    log(f"Fetching weather history for {len(missing)} new project(s)...")
    try:
        fresh = build_climatology_cache(missing, log=log)
    except RuntimeError as e:
        log(f"  weather skipped (offline?): {e}")
        return 0
    if cache:
        cache["projects"].update(fresh["projects"])
    else:
        cache = fresh
    cache_path.write_text(json.dumps(cache, indent=1))
    return len(missing)


class Watcher:
    def __init__(self, xlsx: Path = XLSX, pdfs: list[Path] = PDFS, processed: Path = PROCESSED,
                 state_file: Path = STATE_FILE, weather: bool = True, log=print,
                 run_pipeline=None, export=export_and_recompute):
        self.xlsx, self.pdfs, self.processed = xlsx, pdfs, processed
        self.state_file, self.weather, self.log = state_file, weather, log
        self.export = export
        self.run_pipeline = run_pipeline or self._default_pipeline
        self.state = json.loads(state_file.read_text()) if state_file.exists() else {}

    @staticmethod
    def _default_pipeline():
        from backend.ingest import pipeline

        if pipeline.main(["--weather"]) != 0:
            raise RuntimeError("PDF pipeline exited with an error")

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=1))

    def tick(self) -> list[str]:
        """Rebuild whatever changed since the last tick. Returns what ran."""
        ran = []
        xlsx_now = _mtimes([self.xlsx])
        if xlsx_now and xlsx_now != self.state.get("xlsx"):
            self.log(f"[watch] {self.xlsx.name} changed -> re-export + recompute overlaps")
            # Record the mtime either way: a failed read (e.g. Excel mid-save)
            # is retried on the next save, not every few seconds.
            self.state["xlsx"] = xlsx_now
            try:
                self.export(self.xlsx, self.processed, log=self.log)
                ran.append("xlsx")
                if self.weather:
                    refresh_weather(self.processed / "projects.json", self.processed / "weather_climatology.json", self.log)
            except Exception as e:
                self.log(f"[watch] couldn't read {self.xlsx.name} ({e}); will retry on its next save")
                ran.append("xlsx-failed")

        pdf_now = _mtimes(self.pdfs)
        if pdf_now and "pdfs" not in self.state:
            # First start: record a baseline instead of launching a full
            # geocoding run (network + minutes) by surprise.
            self.state["pdfs"] = pdf_now
            self._save()
            if not (self.processed / "auto" / "projects_auto.json").exists():
                self.log("[watch] tip: run `python3 -m backend.ingest.pipeline` once to build the auto dataset")
        elif pdf_now and pdf_now != self.state.get("pdfs"):
            self.log("[watch] source PDF changed -> re-run PDF ingest pipeline")
            self.state["pdfs"] = pdf_now  # retry on the next change, not every tick
            try:
                self.run_pipeline()
                ran.append("pdfs")
            except Exception as e:  # keep watching
                self.log(f"[watch] pipeline failed: {e}; will retry when a PDF changes again")
                ran.append("pdfs-failed")

        if ran:
            self._save()
        return ran

    def loop(self, interval: float = 3.0):
        self.log(f"[watch] watching {self.xlsx.name} and {len(self.pdfs)} PDFs every {interval:g}s (Ctrl+C to stop)")
        try:
            while True:
                self.tick()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.log("[watch] stopped")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="rebuild anything stale, then exit")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--no-weather", action="store_true", help="don't fetch weather for new projects")
    ap.add_argument("--no-pdfs", action="store_true", help="only watch the spreadsheet")
    args = ap.parse_args(argv)
    w = Watcher(pdfs=[] if args.no_pdfs else PDFS, weather=not args.no_weather)
    if args.once:
        ran = w.tick()
        print("[watch] up to date" if not ran else f"[watch] rebuilt: {', '.join(ran)}")
    else:
        w.loop(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
