import sys,threading,time
from phoenix_forge.util import run_supervised

def test_supervisor_completes_clean_process():
    code,out,err,meta=run_supervised([sys.executable,'-c','print("ok")'],5)
    assert code==0 and out.strip()=='ok' and meta['termination_reason'] is None

def test_supervisor_stops_process_on_safety_event():
    event=threading.Event();threading.Timer(.15,event.set).start()
    code,out,err,meta=run_supervised([sys.executable,'-c','import time;time.sleep(30)'],5,cancel_event=event,poll_interval=.02)
    assert code==125 and meta['terminated'] and meta['termination_reason']=='SAFETY_ABORT'

def test_native_sources_expose_real_kernels():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    header=(root/'native/src/cpu_bench.hpp').read_text()
    main=(root/'native/src/main.cpp').read_text()
    assert 'std::memcpy' in header and 'nanoseconds_per_access' in header
    assert 'cpu-bench' in main and 'memory-bench' in main and 'cache-bench' in main
