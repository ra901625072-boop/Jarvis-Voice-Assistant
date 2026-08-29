"""
apps/backend/ai/agents/research/tools/file_search.py
Tabular Data Analyzer for Market Statistics, Competitor Matrices, Pricing Sheets, and Financials (CSV, JSON, Excel).
"""
import json
import csv
import io
import os
import asyncio
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("JARVIS.ResearchTools.FileSearch")


class ResearchDataAnalyzer:
    """
    Parses and summarizes structured data files (CSV, Excel, JSON) into tabular evidence and comparison matrices.
    """

    @classmethod
    async def analyze_tabular_file(cls, file_path: str) -> Dict[str, Any]:
        """Reads CSV or JSON or Excel and returns column metrics and sample records."""
        if not os.path.exists(file_path):
            return {"error": f"File does not exist: {file_path}"}

        def _do_read():
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".csv":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    return {
                        "format": "csv",
                        "total_rows": len(rows),
                        "columns": reader.fieldnames or [],
                        "sample": rows[:10],
                    }
            elif ext == ".json":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {
                            "format": "json_list",
                            "total_rows": len(data),
                            "sample": data[:10],
                        }
                    elif isinstance(data, dict):
                        return {
                            "format": "json_dict",
                            "keys": list(data.keys()),
                            "sample": {k: data[k] for k in list(data.keys())[:10]},
                        }
            return {"error": f"Unsupported file format '{ext}'"}

        return await asyncio.to_thread(_do_read)

    @classmethod
    def generate_markdown_comparison_table(
        cls,
        headers: List[str],
        rows: List[List[Any]],
        caption: str = ""
    ) -> str:
        """Generates a clean GFM markdown table for competitor / benchmark comparisons."""
        if not headers or not rows:
            return ""

        md = ""
        if caption:
            md += f"**Table: {caption}**\n\n"

        header_line = "| " + " | ".join(str(h) for h in headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        md += f"{header_line}\n{sep_line}\n"

        for row in rows:
            formatted_cells = []
            for i in range(len(headers)):
                cell_val = str(row[i]) if i < len(row) else "-"
                # Escape pipe character in table cell
                cell_val = cell_val.replace("|", "\\|").replace("\n", " ")
                formatted_cells.append(cell_val)
            md += "| " + " | ".join(formatted_cells) + " |\n"

        return md + "\n"
