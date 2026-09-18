from phoenix_forge.models import DetectReport,GPUInfo
from phoenix_forge.modules import benchmark,baseline,health

def report():
    return DetectReport(hostname="x",os="Windows",os_version="x",architecture="AMD64",cpu="Xeon",logical_cpus=8,
      ram_total_bytes=16*1024**3,vulkan_available=True,gpus=[GPUInfo(name="RX",pnp_device_id=r"PCI\VEN_1002&DEV_6FDF\1")])
def row(name,module,metrics):
    return {"name":name,"valid_score":True,"result":{"module":module,"passed":True,"duration_s":1,"metrics":{"status":"PASS",**metrics},"warnings":[]},"telemetry":{}}
def suite():
    return {"score_valid":True,"benchmarks":[
      row("cpu_single","Phoenix Benchmark / CPU Integer",{"operations_per_second":100}),
      row("memory_copy","Phoenix Benchmark / Memory Copy",{"median_mb_s":1000}),
      row("storage_sequential","Phoenix Storage / Sequential",{"read_mb_s":500,"write_mb_s":400}),
      row("gpu_compute","Phoenix Crucible / GPU Compute",{})]}

def test_sensor_timeline_summary():
    result=benchmark.summarize_timeline([{"t_s":0,"cpu_percent":10},{"t_s":1,"cpu_percent":30}])
    assert result["sample_count"]==2
    assert result["summary"]["cpu_percent"]["avg"]==20

def test_invalid_score_when_result_fails():
    from phoenix_forge.models import StressResult
    payload={"model_dump":False}
    # The suite/health contract is independently exercised without running hardware.
    bad={"score_valid":False,"benchmarks":[]}
    assert health.assess(report(),benchmark=bad)["subsystems"]["benchmark"]["health"]=="DEGRADED"

def test_golden_baseline_is_immutable(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    h=health.assess(report(),benchmark=suite())
    assert h["overall"]=="HEALTHY"
    baseline.create(report(),suite(),h)
    try:baseline.create(report(),suite(),h)
    except FileExistsError:pass
    else:raise AssertionError("Golden Baseline was overwritten")
    current=suite();current["benchmarks"][0]["result"]["metrics"]["operations_per_second"]=75
    comparison=baseline.compare(report(),current)
    assert comparison["regressions"][0]["delta_percent"]==-25
