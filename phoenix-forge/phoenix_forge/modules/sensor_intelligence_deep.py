from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any, Iterable

SCHEMA="phoenix.forge.sensor-intelligence-deep/v1"
PRODUCT="Phoenix Sensor Intelligence"

SENSOR_CONSENSUS="SENSOR_CONSENSUS"
SENSOR_CONFLICT="SENSOR_CONFLICT"
SENSOR_STALE="SENSOR_STALE"
SENSOR_DISAPPEARED="SENSOR_DISAPPEARED"
SENSOR_IMPLAUSIBLE="SENSOR_IMPLAUSIBLE"
SENSOR_UNKNOWN="SENSOR_UNKNOWN"

@dataclass
class NormalizedSensor:
    sensor_key:str
    kind:str
    value:float|None
    unit:str|None
    source:str
    source_id:str|None
    hardware_scope:str|None
    timestamp:float|None
    confidence:str
    provenance:str
    raw_name:str|None=None

def _f(v:Any)->float|None:
    try:
        x=float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None

def _norm_name(v:Any)->str:
    s=str(v or "").strip().lower()
    out=[]
    for ch in s:
        out.append(ch if ch.isalnum() else "-")
    return "-".join(filter(None,"".join(out).split("-")))

def normalize_sensor(row:dict[str,Any])->NormalizedSensor:
    kind=str(row.get("kind") or "unknown")
    source=str(row.get("source") or row.get("provider") or "unknown")
    raw_name=str(row.get("name") or row.get("label") or row.get("sensor") or "")
    scope=str(row.get("hardware_scope") or row.get("device_key") or row.get("scope") or "") or None
    source_id=str(row.get("source_id") or row.get("id") or "") or None
    value=_f(row.get("value"))
    unit=row.get("unit")
    ts=_f(row.get("timestamp"))
    conf=str(row.get("confidence") or "MEDIUM").upper()
    prov=str(row.get("provenance") or "AUTHORITATIVE").upper()
    key=str(row.get("sensor_key") or "")
    if not key:
        key=":".join(filter(None,[scope or "host",kind,_norm_name(raw_name) or source_id or "sensor"]))
    return NormalizedSensor(
        sensor_key=key,kind=kind,value=value,unit=unit,source=source,source_id=source_id,
        hardware_scope=scope,timestamp=ts,confidence=conf,provenance=prov,raw_name=raw_name or None
    )

def _plausibility(kind:str,value:float|None)->tuple[bool,str|None]:
    if value is None:
        return False,"missing_or_non_numeric"
    ranges={
        "temperature_c":(-80.0,180.0),
        "fan_rpm":(0.0,30000.0),
        "fan_percent":(0.0,100.0),
        "fan_pwm_percent":(0.0,100.0),
        "voltage_v":(0.0,30.0),
        "power_w":(0.0,5000.0),
        "current_a":(0.0,500.0),
        "clock_mhz":(0.0,100000.0),
        "utilization_percent":(0.0,100.0),
    }
    if kind not in ranges:
        return True,None
    lo,hi=ranges[kind]
    if not (lo<=value<=hi):
        return False,f"outside_plausible_range:{lo}..{hi}"
    return True,None

def _tolerance(kind:str,values:list[float])->float:
    if kind=="temperature_c":
        return 5.0
    if kind in {"fan_percent","fan_pwm_percent","utilization_percent"}:
        return 8.0
    if kind=="fan_rpm":
        return max(150.0,(max(values)-min(values))*0.20 if values else 150.0)
    if kind=="voltage_v":
        return 0.25
    if kind=="power_w":
        return max(10.0,(sum(values)/len(values))*0.15 if values else 10.0)
    if kind=="clock_mhz":
        return max(100.0,(sum(values)/len(values))*0.08 if values else 100.0)
    return max(1.0,(sum(values)/len(values))*0.10 if values else 1.0)

def analyze(readings:Iterable[dict[str,Any]], *, now:float|None=None, stale_after_s:float=15.0,
            previous_keys:Iterable[str]|None=None)->dict[str,Any]:
    now=float(now if now is not None else time.time())
    norm=[normalize_sensor(r) for r in readings]
    previous=set(previous_keys or [])
    present={x.sensor_key for x in norm}
    disappeared=sorted(previous-present)

    by_key=defaultdict(list)
    events=[]
    for x in norm:
        ok,reason=_plausibility(x.kind,x.value)
        if not ok:
            events.append({
                "sensor_key":x.sensor_key,"state":SENSOR_IMPLAUSIBLE,"source":x.source,
                "value":x.value,"unit":x.unit,"reason":reason,"confidence":"HIGH"
            })
            continue
        if x.timestamp is not None and now-x.timestamp>stale_after_s:
            events.append({
                "sensor_key":x.sensor_key,"state":SENSOR_STALE,"source":x.source,
                "value":x.value,"unit":x.unit,
                "age_s":round(now-x.timestamp,3),"threshold_s":stale_after_s,"confidence":"HIGH"
            })
            continue
        by_key[x.sensor_key].append(x)

    consensus=[]
    for key,items in sorted(by_key.items()):
        vals=[x.value for x in items if x.value is not None]
        kind=items[0].kind if items else "unknown"
        if not vals:
            events.append({"sensor_key":key,"state":SENSOR_UNKNOWN,"reason":"no_usable_values","confidence":"HIGH"})
            continue
        if len(items)==1:
            consensus.append({
                "sensor_key":key,"state":SENSOR_UNKNOWN,"kind":kind,
                "value":vals[0],"unit":items[0].unit,
                "sources":[items[0].source],
                "reason":"single_source_no_consensus_claim",
                "confidence":items[0].confidence,
            })
            continue

        tol=_tolerance(kind,vals)
        spread=max(vals)-min(vals)
        if spread<=tol:
            ordered=sorted(vals)
            mid=len(ordered)//2
            central=ordered[mid] if len(ordered)%2 else (ordered[mid-1]+ordered[mid])/2
            consensus.append({
                "sensor_key":key,"state":SENSOR_CONSENSUS,"kind":kind,
                "value":round(central,4),"unit":items[0].unit,
                "sources":[x.source for x in items],
                "spread":round(spread,4),"tolerance":round(tol,4),
                "confidence":"HIGH",
                "method":"central_observation_with_spread_check",
            })
        else:
            events.append({
                "sensor_key":key,"state":SENSOR_CONFLICT,"kind":kind,
                "values":[{"source":x.source,"value":x.value,"unit":x.unit} for x in items],
                "spread":round(spread,4),"tolerance":round(tol,4),
                "reason":"sources_disagree_beyond_tolerance",
                "confidence":"HIGH",
            })

    for key in disappeared:
        events.append({
            "sensor_key":key,"state":SENSOR_DISAPPEARED,
            "reason":"present_in_previous_snapshot_but_missing_now","confidence":"HIGH"
        })

    state_counts=defaultdict(int)
    for x in consensus:
        state_counts[x["state"]]+=1
    for x in events:
        state_counts[x["state"]]+=1

    return {
        "schema":SCHEMA,
        "product":PRODUCT,
        "generated_at":now,
        "summary":{
            "input_readings":len(norm),
            "normalized_keys":len({x.sensor_key for x in norm}),
            "consensus_records":len(consensus),
            "events":len(events),
            "states":dict(state_counts),
        },
        "consensus":consensus,
        "events":events,
        "normalized":[asdict(x) for x in norm],
        "policy":{
            "read_only":True,
            "capability_first":True,
            "makes_placement_decisions":False,
            "blind_averaging_for_conflicting_sources":False,
            "unknown_is_not_zero":True,
            "implausible_values_are_not_silently_accepted":True,
            "single_source_is_not_called_consensus":True,
        }
    }

def capability_summary()->dict[str,Any]:
    return {
        "schema":"phoenix.forge.sensor-intelligence-capabilities/v1",
        "product":PRODUCT,
        "states":[
            SENSOR_CONSENSUS,SENSOR_CONFLICT,SENSOR_STALE,
            SENSOR_DISAPPEARED,SENSOR_IMPLAUSIBLE,SENSOR_UNKNOWN
        ],
        "domains":{
            "motherboard":"RUNTIME_DEPENDENT",
            "chipset":"RUNTIME_DEPENDENT",
            "vrm":"RUNTIME_DEPENDENT",
            "fan_tachometer":"RUNTIME_DEPENDENT",
            "fan_pwm":"RUNTIME_DEPENDENT",
            "voltage_rails":"RUNTIME_DEPENDENT",
            "super_io":"RUNTIME_DEPENDENT",
            "gpu":"RUNTIME_DEPENDENT",
            "cpu":"RUNTIME_DEPENDENT",
        },
        "limitations":[
            "Forge does not invent motherboard/VRM/rail sensors not exposed by an active provider.",
            "Super I/O chip support depends on safe provider access and vendor/chip documentation.",
            "Cross-provider correlation requires stable sensor identity; ambiguous identities stay separate.",
        ],
        "policy":{
            "read_only":True,
            "provider_provenance_required":True,
            "no_blind_average":True,
            "no_false_consensus":True,
        }
    }
