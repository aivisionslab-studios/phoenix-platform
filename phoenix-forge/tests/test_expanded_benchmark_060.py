import tempfile,time
from phoenix_forge.modules import benchmark,storage,diagnostics

def test_distribution_percentiles():
    d=benchmark.distribution([1,2,3,4,100])
    assert d["p50"]==3
    assert d["p95"]>4

def test_cpu_kernels_are_correctness_gated():
    assert benchmark.cpu_floating(.2).metrics["correctness_verified"]
    assert benchmark.cpu_hash(.2).metrics["correctness_verified"]
    assert benchmark.cpu_compression(1,1).metrics["correctness_verified"]
    assert benchmark.memory_latency(1,1000).metrics["correctness_verified"]

def test_random_storage_has_iops_and_latency():
    with tempfile.TemporaryDirectory() as d:
        r=storage.random_bench(16,4,100,d)
    assert r.passed
    assert r.metrics["read_iops"]>0
    assert r.metrics["read_latency"]["p95_ms"]>=0

def test_thermal_guard_requests_abort():
    t=benchmark.SensorTimeline(.1,collector=lambda:{"temperatures":{"cpu_package":{"current":95}}},
      limits={"cpu_temperature":90}).start()
    time.sleep(.15);result=t.stop()
    assert result["abort_requested"]
    assert result["safety_violations"]

def test_diagnostic_plan_stops_invalid_scores():
    h={"overall":"DEGRADED","subsystems":{"gpu":{"health":"HEALTHY","global_ai_blocked":False}}}
    b={"benchmarks":[{"name":"cpu","valid_score":False,"invalid_reason":"safety_limit_exceeded",
      "result":{"metrics":{"status":"PASS"}},"telemetry":{"safety_violations":[]}}]}
    p=diagnostics.plan(h,b,{"devices":[]})
    assert not p["safe_to_continue"]
    assert p["actions"][0]["priority"]=="IMMEDIATE"
