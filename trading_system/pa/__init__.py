"""
Price Action Module
====================
Pattern candlestick + livelli S&R classici integrati con SMC + ML.

Uso:
    from trading_system.pa import analyze_pa, PASignal
    pa = analyze_pa(df, symbol="XAUUSD", direction_hint="long", atr=atr_value)
    if pa.has_confirmation:
        print(f"PA confermata: {pa.pattern_names} | Score: {pa.score}")
"""

from .detector import analyze_pa, PASignal
from .patterns import detect_all_patterns, CandlePattern
from .levels   import find_nearby_levels, SRLevel

__all__ = [
    "analyze_pa", "PASignal",
    "detect_all_patterns", "CandlePattern",
    "find_nearby_levels", "SRLevel",
]
