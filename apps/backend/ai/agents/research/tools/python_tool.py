"""
apps/backend/ai/agents/research/tools/python_tool.py
Python Calculation Sandbox for Statistical Analysis, CAGR Calculations, Currency Normalization, and Pricing Metrics.
"""
import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("JARVIS.ResearchTools.PythonTool")


class ResearchPythonSandbox:
    """
    Executes deterministic mathematical and statistical calculations for deep research.
    """

    @classmethod
    def calculate_cagr(cls, start_value: float, end_value: float, periods: int) -> Dict[str, Any]:
        """
        Calculates Compound Annual Growth Rate (CAGR).
        Formula: CAGR = (end_value / start_value) ** (1 / periods) - 1
        """
        if start_value <= 0 or periods <= 0:
            return {"error": "Invalid start_value or periods"}

        try:
            cagr = ((end_value / start_value) ** (1.0 / periods)) - 1.0
            return {
                "start_value": start_value,
                "end_value": end_value,
                "periods": periods,
                "cagr_decimal": round(cagr, 4),
                "cagr_percentage": round(cagr * 100.0, 2),
            }
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def calculate_summary_stats(cls, values: List[float]) -> Dict[str, Any]:
        """Computes mean, median, min, max, std_dev for a list of numerical claims."""
        if not values:
            return {}

        clean_vals = sorted([v for v in values if isinstance(v, (int, float)) and not math.isnan(v)])
        if not clean_vals:
            return {}

        n = len(clean_vals)
        mean_val = sum(clean_vals) / n
        median_val = clean_vals[n // 2] if n % 2 != 0 else (clean_vals[n // 2 - 1] + clean_vals[n // 2]) / 2.0
        variance = sum((x - mean_val) ** 2 for x in clean_vals) / n
        std_dev = math.sqrt(variance)

        return {
            "count": n,
            "min": clean_vals[0],
            "max": clean_vals[-1],
            "mean": round(mean_val, 2),
            "median": round(median_val, 2),
            "std_dev": round(std_dev, 2),
        }

    @classmethod
    def normalize_pricing_to_monthly(cls, amount: float, billing_cycle: str) -> float:
        """Converts annual / quarterly / weekly pricing to monthly equivalent."""
        cycle = billing_cycle.lower()
        if "year" in cycle or "annual" in cycle:
            return round(amount / 12.0, 2)
        elif "quarter" in cycle:
            return round(amount / 3.0, 2)
        elif "week" in cycle:
            return round(amount * 4.33, 2)
        elif "day" in cycle:
            return round(amount * 30.0, 2)
        return round(amount, 2)
