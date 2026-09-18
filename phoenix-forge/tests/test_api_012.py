import time

from phoenix_forge.api.app import health_check


def test_liveness_is_fast_and_does_not_run_hardware_discovery():
    started=time.monotonic();result=health_check();elapsed=time.monotonic()-started
    assert result=={"ok":True,"product":"Phoenix Forge","version":"0.12.0","service":"alive"}
    assert elapsed<0.25
