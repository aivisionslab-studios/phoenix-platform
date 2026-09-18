# Phoenix Forge 0.19.9

Hardware intelligence, diagnostics, qualification and evidence-aware setup analysis for Phoenix.

0.19.8 adds a conservative Configuration Auditor. It does not invent PCIe bandwidth, memory channels, thermal throttling, NUMA affinity or storage bottlenecks when the required provider/measurement is absent.


## 0.19.9
Adds measured PCIe link intelligence and an explicit capability registry driven by the 0.19.8 full audit.

## 0.20.0 Audit Architecture
A release 0.20.0 transforma a auditoria de paridade em contratos de runtime: NVMe deep inspection, sensor fusion, provider contracts privilegiados, gap tracker e recomendacoes baseadas em evidencia.


## 0.20.6 — Safe Provider Execution Runtime
Providers privilegiados verificados agora podem executar apenas capabilities read-only declaradas, via protocolo JSON versionado, com timeout, limite de payload, audit trail e circuit breaker.


## 0.20.7
Adds provider-backed MSR clock intelligence and non-blocking telemetry send reliability. Actual MSR values remain runtime-dependent on a verified provider.

## 0.21.1 — Scheduler Execution Policy
Adds persistent device leases, Safety revalidation immediately before dispatch, SINGLE/PARALLEL assignment generation, plan→dispatch→result correlation, cancellation and CPU fallback. Backend execution remains separate; COOPERATIVE still requires a backend-specific executor.
