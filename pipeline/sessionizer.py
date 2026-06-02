"""Event-generation FSM (pure Python, no torch — unit-testable).

Consumes time-ordered per-person Observations (produced by the YOLO/ByteTrack
driver in detect.py) and emits behavioural events in the production schema.

One FSM instance handles the whole store. Re-entry is detected per visitor_id:
an 'enter' boundary after a prior 'exit' becomes REENTRY, never a second ENTRY —
so re-entries don't inflate visitor counts. Low-confidence detections are NOT
dropped; their confidence is carried onto the event for the API to weigh.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

DWELL_INTERVAL_S = 30
# ignore a second doorway crossing within this many seconds of the last one —
# collapses the foot-oscillation that happens when a visitor loiters on the line
CROSSING_DEBOUNCE_S = 4.0


@dataclass
class Observation:
    visitor_id: str
    camera_id: str
    ts: datetime
    zone_id: str | None = None
    boundary: str | None = None        # 'enter' | 'exit' | None (entry-line)
    is_staff: bool = False
    confidence: float = 0.9
    queue_depth: int | None = None     # crowd count in billing zone at this frame


@dataclass
class _VState:
    current_zone: str | None = None
    zone_enter_ts: datetime | None = None
    dwell_emits: int = 0
    in_store: bool = False
    has_exited: bool = False
    purchased: bool = False
    seq: int = 0
    last_boundary_ts: datetime | None = None  # for crossing debounce


class Sessionizer:
    def __init__(self, store_id: str, is_billing=lambda z: z == "BILLING"):
        self.store_id = store_id
        self.is_billing = is_billing
        self._state: dict[str, _VState] = {}
        self.events: list[dict] = []

    # ---- emission helpers ----
    def _emit(self, obs: Observation, etype: str, *, zone_id=None, dwell_ms=0,
              queue_depth=None):
        st = self._state[obs.visitor_id]
        st.seq += 1
        self.events.append({
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": obs.camera_id,
            "visitor_id": obs.visitor_id,
            "event_type": etype,
            "timestamp": obs.ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "zone_id": zone_id,
            "dwell_ms": int(dwell_ms),
            "is_staff": obs.is_staff,
            "confidence": round(float(obs.confidence), 3),
            "metadata": {
                "queue_depth": queue_depth,
                "sku_zone": zone_id,
                "session_seq": st.seq,
            },
        })

    # ---- main entry ----
    def observe(self, obs: Observation) -> None:
        st = self._state.get(obs.visitor_id)
        if st is None:
            st = self._state[obs.visitor_id] = _VState()

        # 1) doorway boundary crossings (debounced against loiter oscillation)
        boundary = obs.boundary
        if boundary in ("enter", "exit") and st.last_boundary_ts is not None:
            if (obs.ts - st.last_boundary_ts).total_seconds() < CROSSING_DEBOUNCE_S:
                boundary = None  # too soon after the last crossing -> ignore

        if boundary == "enter":
            # only a real state change counts (outside -> inside)
            if not st.in_store:
                self._emit(obs, "REENTRY" if st.has_exited else "ENTRY")
                st.in_store = True
                st.has_exited = False
                st.last_boundary_ts = obs.ts
        elif boundary == "exit":
            if st.in_store:
                self._close_zone(obs)
                self._emit(obs, "EXIT")
                st.in_store = False
                st.has_exited = True
                st.last_boundary_ts = obs.ts
                return

        # 2) zone transitions
        if obs.zone_id != st.current_zone:
            self._close_zone(obs)
            if obs.zone_id is not None:
                self._emit(obs, "ZONE_ENTER", zone_id=obs.zone_id)
                if self.is_billing(obs.zone_id) and (obs.queue_depth or 0) > 0:
                    self._emit(obs, "BILLING_QUEUE_JOIN", zone_id=obs.zone_id,
                               queue_depth=obs.queue_depth)
                st.current_zone = obs.zone_id
                st.zone_enter_ts = obs.ts
                st.dwell_emits = 0
        else:
            # 3) continued dwell -> emit every 30s
            if st.zone_enter_ts is not None and obs.zone_id is not None:
                elapsed = (obs.ts - st.zone_enter_ts).total_seconds()
                while elapsed >= (st.dwell_emits + 1) * DWELL_INTERVAL_S:
                    st.dwell_emits += 1
                    self._emit(obs, "ZONE_DWELL", zone_id=obs.zone_id,
                               dwell_ms=st.dwell_emits * DWELL_INTERVAL_S * 1000)

    def _close_zone(self, obs: Observation) -> None:
        """Emit ZONE_EXIT (and a billing abandon if leaving billing unpaid)."""
        st = self._state[obs.visitor_id]
        if st.current_zone is None or st.zone_enter_ts is None:
            return
        dwell_ms = (obs.ts - st.zone_enter_ts).total_seconds() * 1000
        leaving = st.current_zone
        self._emit(obs, "ZONE_EXIT", zone_id=leaving, dwell_ms=dwell_ms)
        if self.is_billing(leaving) and not st.purchased:
            self._emit(obs, "BILLING_QUEUE_ABANDON", zone_id=leaving)
        st.current_zone = None
        st.zone_enter_ts = None
        st.dwell_emits = 0

    def close(self) -> list[dict]:
        """Flush open zones at end-of-stream and return all events sorted by time."""
        # emit a final ZONE_EXIT for anyone still in a zone, anchored to last seen ts
        for vid, st in self._state.items():
            if st.current_zone is not None and st.zone_enter_ts is not None:
                st.seq += 1
                self.events.append({
                    "event_id": str(uuid.uuid4()),
                    "store_id": self.store_id,
                    "camera_id": "-",
                    "visitor_id": vid,
                    "event_type": "ZONE_EXIT",
                    "timestamp": st.zone_enter_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "zone_id": st.current_zone,
                    "dwell_ms": 0,
                    "is_staff": False,
                    "confidence": 0.5,
                    "metadata": {"queue_depth": None, "sku_zone": st.current_zone,
                                 "session_seq": st.seq},
                })
                st.current_zone = None
        self.events.sort(key=lambda e: e["timestamp"])
        return self.events


def process_observations(store_id: str, observations: list[Observation],
                         is_billing=lambda z: z == "BILLING") -> list[dict]:
    s = Sessionizer(store_id, is_billing=is_billing)
    for obs in sorted(observations, key=lambda o: o.ts):
        s.observe(obs)
    return s.close()
