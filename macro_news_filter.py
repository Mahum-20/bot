"""
Macro Economic News Event Filter
=================================
Monitors high-impact macroeconomic releases:
1. US Consumer Price Index (CPI)
2. Federal Open Market Committee (FOMC) Rate Decisions & Statements
3. US Non-Farm Payrolls (NFP)

Automatically pauses trading entries within a configurable time buffer (default: +/- 2.5 hours)
around high-impact events to prevent whipsaw stop-outs.
"""

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger("MacroNewsFilter")

# Master Schedule of Major US Macro Events (CPI, FOMC, NFP) for 2025 - 2027
# Format: (Date "YYYY-MM-DD", UTC hour float, Event Name, Impact Description)
MACRO_CALENDAR: List[Tuple[str, float, str, str]] = [
    # 2025 Releases
    ("2025-10-03", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2025-10-15", 12.5, "CPI", "US Consumer Price Index"),
    ("2025-11-05", 18.0, "FOMC", "Fed Interest Rate Decision"),
    ("2025-11-07", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2025-11-13", 13.5, "CPI", "US Consumer Price Index"),
    ("2025-12-05", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2025-12-11", 13.5, "CPI", "US Consumer Price Index"),
    ("2025-12-17", 19.0, "FOMC", "Fed Rate Decision & Projections"),

    # 2026 Releases
    ("2026-01-09", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-01-14", 13.5, "CPI", "US Consumer Price Index"),
    ("2026-01-28", 19.0, "FOMC", "Fed Interest Rate Decision"),
    ("2026-02-06", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-02-12", 13.5, "CPI", "US Consumer Price Index"),
    ("2026-03-06", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-03-11", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-03-18", 18.0, "FOMC", "Fed Rate Decision & Projections"),
    ("2026-04-03", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-04-14", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-05-06", 18.0, "FOMC", "Fed Interest Rate Decision"),
    ("2026-05-08", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-05-13", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-06-05", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-06-10", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-06-17", 18.0, "FOMC", "Fed Rate Decision & Projections"),
    ("2026-07-03", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-07-15", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-07-29", 18.0, "FOMC", "Fed Interest Rate Decision"),
    ("2026-08-07", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-08-12", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-09-04", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-09-11", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-09-16", 18.0, "FOMC", "Fed Rate Decision & Projections"),
    ("2026-10-02", 12.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-10-14", 12.5, "CPI", "US Consumer Price Index"),
    ("2026-11-04", 19.0, "FOMC", "Fed Interest Rate Decision"),
    ("2026-11-06", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-11-12", 13.5, "CPI", "US Consumer Price Index"),
    ("2026-12-04", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2026-12-10", 13.5, "CPI", "US Consumer Price Index"),
    ("2026-12-16", 19.0, "FOMC", "Fed Rate Decision & Projections"),

    # 2027 Projections
    ("2027-01-08", 13.5, "NFP", "US Non-Farm Payrolls"),
    ("2027-01-13", 13.5, "CPI", "US Consumer Price Index"),
    ("2027-01-27", 19.0, "FOMC", "Fed Interest Rate Decision"),
    ("2027-03-17", 18.0, "FOMC", "Fed Rate Decision & Projections")
]

class MacroNewsFilter:
    def __init__(self, enabled: bool = True, buffer_hours: float = 2.5):
        self.enabled = enabled
        self.buffer_hours = buffer_hours
        self.raw_events = list(MACRO_CALENDAR)
        
        # Precompute timestamp windows for fast & exact lookups
        self.parsed_events = []
        for ev_date, ev_hour, ev_name, ev_desc in self.raw_events:
            hour_int = int(ev_hour)
            min_int = int(round((ev_hour - hour_int) * 60))
            ev_dt = datetime.strptime(f"{ev_date} {hour_int:02d}:{min_int:02d}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            self.parsed_events.append({
                "date": ev_date,
                "hour": ev_hour,
                "name": ev_name,
                "desc": ev_desc,
                "dt": ev_dt,
                "ts": ev_dt.timestamp()
            })

    def _normalize_timestamp(self, dt: Optional[object] = None) -> float:
        if dt is None:
            return datetime.now(timezone.utc).timestamp()
        if isinstance(dt, (int, float)):
            # Convert milliseconds to seconds if needed
            return (dt / 1000.0) if dt > 1e11 else float(dt)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        return datetime.now(timezone.utc).timestamp()

    def is_macro_event_active(self, dt: Optional[object] = None) -> Tuple[bool, Optional[str], float]:
        """
        Checks if the provided timestamp/datetime (or current UTC time) falls within a macro news window.
        Returns: (is_active: bool, event_name: Optional[str], hours_from_release: float)
        """
        if not self.enabled:
            return False, None, 0.0

        target_ts = self._normalize_timestamp(dt)
        buffer_sec = self.buffer_hours * 3600.0

        for ev in self.parsed_events:
            diff_sec = abs(target_ts - ev["ts"])
            if diff_sec <= buffer_sec:
                diff_hours = diff_sec / 3600.0
                return True, ev["name"], diff_hours

        return False, None, 0.0

    def get_next_macro_event(self, dt: Optional[object] = None) -> Optional[Dict]:
        """Returns the next scheduled macro event."""
        target_ts = self._normalize_timestamp(dt)
        upcoming = []

        for ev in self.parsed_events:
            # Include events within the active buffer or upcoming in the future
            if ev["ts"] >= target_ts - (self.buffer_hours * 3600.0):
                hours_until = (ev["ts"] - target_ts) / 3600.0
                upcoming.append({
                    "date": ev["date"],
                    "event": ev["name"],
                    "description": ev["desc"],
                    "hours_until": round(hours_until, 1),
                    "is_active": abs(hours_until) <= self.buffer_hours
                })

        upcoming.sort(key=lambda x: x["hours_until"])
        return upcoming[0] if upcoming else None

    def get_all_events(self, dt: Optional[object] = None) -> List[Dict]:
        """Returns the full calendar of macro events with relative status."""
        target_ts = self._normalize_timestamp(dt)
        all_events = []

        for ev in self.parsed_events:
            diff_hours = (ev["ts"] - target_ts) / 3600.0
            is_active = abs(diff_hours) <= self.buffer_hours
            
            if diff_hours < -self.buffer_hours:
                status = "COMPLETED"
            elif is_active:
                status = "ACTIVE"
            else:
                status = "UPCOMING"

            hour_int = int(ev["hour"])
            min_int = int(round((ev["hour"] - hour_int) * 60))
            utc_time_str = f"{hour_int:02d}:{min_int:02d} UTC"

            all_events.append({
                "date": ev["date"],
                "event": ev["name"],
                "description": ev["desc"],
                "utc_time": utc_time_str,
                "hours_until": round(diff_hours, 1),
                "is_active": is_active,
                "status": status,
                "buffer_hours": self.buffer_hours
            })

        all_events.sort(key=lambda x: x["hours_until"])
        return all_events

macro_news_engine = MacroNewsFilter()


