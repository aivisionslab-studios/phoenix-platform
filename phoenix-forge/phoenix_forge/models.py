from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

class GPUInfo(BaseModel):
    name: str = 'Unknown GPU'
    device_index: int | None = None
    device_key: str | None = None
    numa_node: int | None = None
    affinity_status: str = 'UNKNOWN'
    affinity_confidence: float = 0.0
    affinity_provenance: list[str] = Field(default_factory=list)
    vendor: str | None = None
    vendor_id: str | None = None
    device_id: str | None = None
    subsystem_vendor_id: str | None = None
    subsystem_device_id: str | None = None
    revision_id: str | None = None
    pnp_device_id: str | None = None
    driver_version: str | None = None
    driver_date: str | None = None
    adapter_ram_bytes: int | None = None
    video_processor: str | None = None
    bus: str | None = None
    vulkan_detected: bool = False
    vulkan_device_name: str | None = None
    vulkan_api_version: str | None = None
    vulkan_memory_heaps: list[dict[str, Any]] = Field(default_factory=list)
    vulkan_memory_types: list[dict[str, Any]] = Field(default_factory=list)
    vulkan_queue_families: list[dict[str, Any]] = Field(default_factory=list)
    vulkan_limits: dict[str, Any] = Field(default_factory=dict)
    vulkan_primary_device_local_bytes: int | None = None
    vram_capacity_source: str | None = None
    dxgi: dict[str, Any] = Field(default_factory=dict)
    vendor_details: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

class DetectReport(BaseModel):
    hostname: str; os: str; os_version: str; architecture: str; cpu: str; logical_cpus: int
    physical_cpus: int | None = None; ram_total_bytes: int
    gpus: list[GPUInfo] = Field(default_factory=list); vulkan_available: bool = False
    tools: dict[str, str | None] = Field(default_factory=dict); motherboard: dict[str, Any] = Field(default_factory=dict); bios: dict[str, Any] = Field(default_factory=dict)
    storage: list[dict[str, Any]] = Field(default_factory=list); capabilities: dict[str, Any] = Field(default_factory=dict); cpu_features: dict[str, Any] = Field(default_factory=dict); compute_fabric: dict[str, Any] = Field(default_factory=dict)

class PulseReport(BaseModel):
    cpu_percent: float; ram_percent: float; ram_used_bytes: int; ram_available_bytes: int
    cpu_freq_mhz: float | None = None; temperatures: dict[str, Any] = Field(default_factory=dict); gpu: list[dict[str, Any]] = Field(default_factory=list)

class StressResult(BaseModel):
    module: str; passed: bool; duration_s: float; metrics: dict[str, Any] = Field(default_factory=dict); warnings: list[str] = Field(default_factory=list)

class ForensicsFinding(BaseModel):
    key: str; value: str; confidence: float = Field(ge=0,le=1); evidence: list[str] = Field(default_factory=list)

class ForensicsReport(BaseModel):
    findings: list[ForensicsFinding] = Field(default_factory=list); notes: list[str] = Field(default_factory=list); risk_flags: list[str] = Field(default_factory=list); confidence_score: int = Field(default=0,ge=0,le=100)

class AIBenchResult(BaseModel):
    backend: str; passed: bool; latency_s: float; tokens_per_second: float | None = None; details: dict[str, Any] = Field(default_factory=dict)

class AutopilotDecision(BaseModel):
    mode: Literal['CPU','GPU','HYBRID']; confidence: float = Field(ge=0,le=1); reasons: list[str]; policy: dict[str, Any] = Field(default_factory=dict)

class CertificationReport(BaseModel):
    detect: DetectReport; forensics: ForensicsReport; pulse: PulseReport; tests: list[StressResult] = Field(default_factory=list); ai: list[AIBenchResult] = Field(default_factory=list); autopilot: AutopilotDecision; score: int = Field(ge=0,le=100)
