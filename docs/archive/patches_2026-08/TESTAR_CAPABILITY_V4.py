from phoenix_kernel.licensing.plans import get_rag_limits
from phoenix_kernel.licensing.commercial_guard import security_status

limits = get_rag_limits(force_refresh=True)
status = security_status()

print("PLAN =", limits["plan"])
print("MAX_DOCUMENTS =", limits["max_documents"])
print("MAX_UPLOAD_MB =", limits["max_upload_bytes"] // (1024 * 1024))
print("MAX_CHARACTERS =", limits["max_characters"])
print("CAPABILITY_VALID =", limits["capability_valid"])
print("CAPABILITY_SOURCE =", limits["capability_source"])
print("FEATURES =", limits["features"])
print("SECURITY =", status)

assert limits["plan"] in {"free", "pro"}
if limits["plan"] == "free":
    assert limits["max_documents"] == 10
    assert limits["max_upload_bytes"] == 25 * 1024 * 1024
    assert limits["max_characters"] == 500_000

print("SMOKE TEST OK")
