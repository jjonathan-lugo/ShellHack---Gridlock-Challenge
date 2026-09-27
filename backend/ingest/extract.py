"""Extract project lists from the two utility PDFs in data/.

DESC  "2024-2028 $2M and above project descriptions": one project per page,
      labelled fields (Project ID, Status, Planned In-Service Date, cost).
GPC   2025 IRP Volume 3, "Table 2 Georgia ITS 10 Year Plan Project List":
      one row per project (zone, year, TEAMS number, name, need date, sponsor),
      with long names wrapping onto the following lines.

Only public fields are read; the cost columns in the GPC filing are REDACTED.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESC_PDF = REPO_ROOT / "data" / "Dominion Engery" / "2024-2028-2million-and-above-project-descriptions.pdf"
GPC_PDF = REPO_ROOT / "data" / "Georgia Power" / "2025 IRP Volume 3 PUBLIC DISCLOSURE.pdf"

DESC_UTILITY = "Dominion Energy South Carolina"
GPC_UTILITY = "Georgia Power"


def _open(path: Path):
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "PDF ingest needs pdfplumber: pip install -r backend/requirements-ingest.txt"
        ) from e
    return pdfplumber.open(str(path))


def normalize_date(raw: str | None) -> str | None:
    """'12/31/23', '6/1/2033', '12/31/2024' -> 'YYYY-MM-DD' (None if unparseable)."""
    if not raw:
        return None
    raw = re.sub(r"\s+", "", raw)
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ---------------- DESC ----------------

_DESC_FIELDS = [
    "Project ID",
    "Project Description",
    "Project Need",
    "Project Status",
    "Planned In-Service Date",
    "Estimated Project Cost",
]


def parse_desc_page(text: str) -> dict | None:
    """One DESC project page -> record (None if the page isn't a project page)."""
    m = re.search(r"Project (\d+) of (\d+)", text)
    if not m or "Project ID" not in text:
        return None
    lines = [ln.strip() for ln in text.splitlines()]

    # Project name: the lines between the "5 Year Budget" banner and "Project ID".
    try:
        start = next(i for i, ln in enumerate(lines) if ln.endswith("5 Year Budget")) + 1
        end = lines.index("Project ID")
    except (StopIteration, ValueError):
        return None
    name = " ".join(ln for ln in lines[start:end] if ln)

    fields: dict[str, str] = {}
    positions = [(lines.index(f), f) for f in _DESC_FIELDS if f in lines]
    positions.sort()
    for (idx, field), nxt in zip(positions, positions[1:] + [(len(lines), None)]):
        fields[field] = " ".join(ln for ln in lines[idx + 1 : nxt[0]] if ln)

    total_cost = None
    costs = re.findall(r"\$[\d,]+", fields.get("Estimated Project Cost", ""))
    if costs:
        total_cost = int(costs[-1].replace("$", "").replace(",", ""))

    # Usually one date; phased projects list several ("10/1/2025 (phase 1) and
    # 10/1/2026 (phase 2)") — use the final phase and keep the original text.
    raw_date = fields.get("Planned In-Service Date", "")
    dates = [normalize_date(d) for d in re.findall(r"\d{1,2}/\d{1,2}/\d{2,4}", raw_date)]
    dates = [d for d in dates if d]

    rec = {
        "source_id": fields.get("Project ID", "").strip(),
        "source_index": int(m.group(1)),
        "utility": DESC_UTILITY,
        "state": "SC",
        "sponsor": "DESC",
        "project_name": re.sub(r"\s+", " ", name).strip(),
        "description": fields.get("Project Description", ""),
        "status": fields.get("Project Status", ""),
        "in_service_date": max(dates) if dates else None,
        "estimated_cost_usd": total_cost,
    }
    if len(dates) > 1:
        rec["in_service_note"] = raw_date
    return rec


def extract_desc_projects(pdf_path: Path = DESC_PDF) -> list[dict]:
    out = []
    with _open(pdf_path) as pdf:
        for page in pdf.pages:
            rec = parse_desc_page(page.extract_text() or "")
            if rec:
                out.append(rec)
    return out


# ---------------- GPC ----------------

_GPC_ROW = re.compile(
    r"^(?P<zone>\d{3}) (?P<year>20\d{2}) (?P<teams>\d{5}) (?P<name>.*?) ?"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4}) (?P<sponsor>[A-Z]+) REDACTED"
)
_GPC_STOP = re.compile(r"^(Total\b|20\d\d GA ITS Ten-Year Plan|B\. Cancelled Projects)")


def parse_gpc_table_page(text: str) -> list[dict]:
    """Rows from one page of Table 2 (the 10-year project list)."""
    lines = [ln.strip() for ln in text.splitlines()]
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("Number 2024 Sponsor")) + 1
    except StopIteration:
        return []

    rows: list[dict] = []
    for ln in lines[start:]:
        if not ln or _GPC_STOP.match(ln):
            if ln and _GPC_STOP.match(ln):
                break
            continue
        m = _GPC_ROW.match(ln)
        if m:
            rows.append({**m.groupdict(), "name_parts": [m.group("name")] if m.group("name") else []})
        elif rows:
            rows[-1]["name_parts"].append(ln)  # wrapped continuation of the name

    out = []
    for r in rows:
        name = re.sub(r"\s+", " ", " ".join(r["name_parts"])).strip()
        name = re.sub(r"\s+-\s*$", "", name)
        out.append(
            {
                "source_id": r["teams"],
                "zone": r["zone"],
                "utility": GPC_UTILITY,
                "state": "GA",
                "sponsor": r["sponsor"],
                "project_name": name,
                "in_service_date": normalize_date(r["date"]),
            }
        )
    return out


def find_gpc_table_pages(pdf) -> list[int]:
    """Indices of Table 2 pages: from the 'A. Georgia ITS 10 Year Expansion Plan
    Projects List' heading up to (not including) the cancelled-projects table."""
    pages, inside = [], False
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if "10 Year Plan Project List" in text:
            inside = True
        if inside and ("Cancelled Projects" in text and "Removed from the Current" in text):
            break
        if inside:
            pages.append(i)
    return pages


def extract_gpc_projects(pdf_path: Path = GPC_PDF, pages: list[int] | None = None) -> list[dict]:
    """All Table 2 rows. Sponsors: GPC, SAV (Georgia Power's Savannah area),
    plus co-owners GTC / MEAG / DU — filter with `sponsor` downstream."""
    out = []
    with _open(pdf_path) as pdf:
        if pages is None:
            pages = _fast_find_table_pages(pdf_path) or find_gpc_table_pages(pdf)
        for i in pages:
            out.extend(parse_gpc_table_page(pdf.pages[i].extract_text() or ""))
    # A project can repeat across a page break; keep the first.
    seen, unique = set(), []
    for r in out:
        if r["source_id"] in seen:
            continue
        seen.add(r["source_id"])
        unique.append(r)
    return unique


def _fast_find_table_pages(pdf_path: Path) -> list[int]:
    """Locate Table 2 with pypdf (much faster than pdfplumber over 668 pages)."""
    try:
        import pypdf
    except ImportError:
        return []
    reader = pypdf.PdfReader(str(pdf_path))
    pages, inside = [], False
    for i, page in enumerate(reader.pages):
        text = re.sub(r"\s+", " ", page.extract_text() or "")
        if re.search(r"10 Year Plan Project List", text):
            inside = True
        if inside and "Cancelled Projects" in text:
            break
        if inside:
            pages.append(i)
    return pages
