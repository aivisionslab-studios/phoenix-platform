# Phoenix Forge 0.25.0rc6.post15 — Windows Evidence Promotion Pipeline

- Windows evidence is promoted capability-by-capability from a signed-by-control-flow run context.
- Verification ledger and capability evidence map are persisted under forge_audit.
- Capability Closure Report overlays only valid current-version Windows evidence.
- Hardware verification remains zero unless a hardware-specific evidence contract is actually satisfied.
- Decision influence remains DISABLED.

## Historical changelog

# Phoenix Forge 0.25.0rc6.post14 — Release Metadata Truth Gate

- pyproject.toml is the canonical release-version source.
- Build/install now fail closed on current-release metadata divergence.
- Historical release artifacts are explicitly classified and may retain their historical labels.
- Hard-coded LaVa User-Agent version strings were replaced by phoenix_forge.__version__.
- Corrupted post13 audit/remediation metadata was repaired to post13 before archival classification.

## Historical changelog

# Phoenix Forge 0.25.0rc6.post12 — Dynamic Verification Semantics Hardening

- Smoke e verification semantics usam contagem derivada do Registry, nunca numero congelado.
- Phoenix LaVa Foundation permanece RUNTIME_DEPENDENT / VERIFIED_SYNTHETIC.

# Phoenix Forge 0.25.0rc6.post12 — Release Integrity + Shadow Hygiene Consolidation

## PEP 440 Release Version Hardening
- project.version agora usa 0.25.0rc6.post12 (PEP 440 valido).
- instalador valida a versao antes de `pip install -e`.
- regressao inclui selftest especifico do version gate.


Base: 0.25.0rc6.post1, Windows install/regression PASS.

Large hardening delivery:
1. METHOD_BUFFERED alias fix.
2. Secure device ACL/SDDL via IoCreateDeviceSecure.
3. Wdmsec.lib linkage.
4. Fail-closed trust gate in the effective MSR data path.
5. Parallel APERF/MPERF sampling.
6. Raw APERF/MPERF evidence preservation.
7. WDK preflight v2 detecting missing WindowsKernelModeDriver10.0 VS integration.
8. Qualification preflight evidence.
9. Privileged driver source readiness v2.
10. Capability Closure Report v3 with global/planned MISSING visibility.
11. INF source version refresh.
12. API/CLI trust inspection.
13. Expanded self-tests.

Still blocked: driver install, service start, test-signing bypass, trusted runtime
promotion, hardware verification and Decision Engine.


# Phoenix Forge 0.25.0rc6.post1 — Unsigned WDK Build Qualification — Matrix Schema Hotfix

Base válida: Phoenix Forge 0.25.0rc5 — Windows verified / WDK_ENVIRONMENT_READY.

Falha do 0.25.0rc6:
- smoke abortou em `matrix_schema`;
- runtime real devolveu `phoenix.forge.capability-matrix/v35`;
- o contrato de Capability Matrix não mudou nesta release e deve permanecer v34;
- o rollback restaurou corretamente 0.25.0rc5.

Correção única:
- `capability_matrix.SCHEMA` restaurado para v34;
- rota/API da matrix restaurada para v34;
- smoke do instalador restaurado para v34;
- selftest de capability-finalization restaurado para v34.

O `capability-registry` continua v35, pois esse contrato realmente ganhou novas capabilities no rc6.

Nenhuma mudança em WDK source, ABI, unsigned qualifier, assinatura, instalação ou política de segurança.


# Phoenix Forge 0.25.0rc6 — Unsigned WDK Build Qualification

Base: 0.25.0rc5 Windows verified; WDK preflight reported `WDK_ENVIRONMENT_READY`.

Objective: qualify a real unsigned WDK build without installing or starting the driver.

Adds:
- `QUALIFY_UNSIGNED_DRIVER.ps1`;
- SHA-256 of the produced `.sys`;
- Authenticode status capture;
- JSON build evidence;
- optional `-KeepBuild`; otherwise the development `.sys` is removed after evidence is captured;
- API/CLI evidence reader.

Safety:
- no pnputil;
- no service creation/start;
- no bcdedit/test-signing;
- no certificate creation;
- unsigned build never promotes `signed_runtime`;
- hardware_verified remains 0.


# Phoenix Forge 0.25.0rc4.post1 — Verification Semantics & Release Metadata Hotfix

Base funcional: Phoenix Forge 0.25.0rc4, Windows validated.

Correções:
- `VERIFIED_SYNTHETIC` não é mais contado como `Hardware verified`;
- Capability Closure Report separa:
  - hardware_verified
  - synthetic_verified
  - windows_verified
  - hardware_unverified
- corrige o FOCO do instalador: o SOURCE anuncia APERF/MPERF, mas o runtime assinado continua ausente;
- nenhuma capability funcional, ABI, IOCTL ou primitive privilegiada mudou.

Resultado esperado nesta base:
- hardware_verified = 0
- synthetic_verified = 3
- signed runtime = EXTERNAL_REQUIRED / UNVERIFIED


# Phoenix Forge 0.25.0rc4 — Allowlisted APERF-MPERF Privileged Read Source

Base congelada: Phoenix Forge 0.25.0rc3.post1 — Windows verified.

Objetivo único: implementar em SOURCE o primeiro caminho privilegiado read-only e allowlisted do driver Phoenix.

Implementado:
- somente MSR `0xE7` (MPERF) e `0xE8` (APERF);
- nenhum endereço MSR vem do user-mode;
- CPUID leaf 6 guard;
- SEH fail-closed em `__readmsr`;
- processor-group affinity validada;
- janela de amostragem limitada a 10..2000 ms;
- deltas APERF/MPERF;
- capability bit APERF/MPERF habilitado no SOURCE.

Ainda não implementado/afirmado:
- driver `.sys` assinado;
- runtime privilegiado instalado;
- hardware verification;
- `reference_mhz` autoritativo.

`reference_mhz` permanece `0.0`, portanto o Forge rejeita corretamente a derivação de effective MHz em vez de inventar uma frequência de referência.


# Phoenix Forge 0.25.0rc3.post1 — Phoenix Privileged Driver Source & ABI Foundation — BAT Escape Hotfix

Base funcional: 0.25.0rc3, validado no Windows com código final 0.

Correção única:
- escapa `&` como `^&` somente nas linhas `echo` dos wrappers CMD/BAT;
- elimina `'ABI' não é reconhecido como um comando interno`;
- nenhuma capability, provider, ABI, driver source, rota ou política mudou.

A release continua source-only para o driver privilegiado.


# Phoenix Forge 0.25.0rc3 — Phoenix Privileged Driver Source & ABI Foundation

Base congelada: Phoenix Forge 0.25.0rc2 — Windows verified.

Objetivo único: criar a fonte e o ABI do futuro driver privilegiado Phoenix sem afirmar acesso privilegiado real.

Implementado:
- source-only Windows kernel driver skeleton;
- device/ABI compatível com `\\.\PhoenixForgeMsr`;
- GET_INFO read-only;
- READ_COUNTER_PAIR reservado mas retorna `STATUS_NOT_SUPPORTED`;
- `capability_bits = 0`;
- IRP_MJ_WRITE bloqueado;
- nenhum `__readmsr`, `__writemsr`, port I/O ou memory mapping;
- INF source template;
- WDK/signing preflight;
- API/CLI/status da source foundation.

Não incluído:
- `.sys`;
- `.cat`;
- certificado/chave;
- driver de terceiros;
- leitura privilegiada real.

Próxima etapa, somente após validação Windows desta RC:
implementar APERF/MPERF allowlisted no driver Phoenix e validá-lo com WDK/hardware, ainda read-only.


# Phoenix Forge 0.25.0rc2 — Privileged Provider Security Contract Foundation

Base congelada: Phoenix Forge 0.25.0rc1.post1 — Windows validated.

Objetivo único: formalizar o contrato de segurança dos futuros providers privilegiados Phoenix.

O contrato:
- é read-only;
- é capability-based, não address-based;
- proíbe MSR arbitrário, port I/O arbitrário, memória física/kernel e writes;
- exige driver Phoenix assinado para qualquer acesso privilegiado real;
- proíbe drivers vulneráveis de terceiros;
- nega requests desconhecidas;
- mantém Intel e AMD como fornecedores de primeira classe;
- mantém Decision Engine, dispatch e orchestration desabilitados.

Esta release NÃO contém um driver kernel assinado e NÃO afirma acesso privilegiado real.


# Phoenix Forge 0.25.0rc1.post1 — CPU Vendor Deep Provider Foundation — Release Polish Hotfix

Base: 0.25.0rc1.

Falha Windows observada:
`selftest_release_polish_02312.py` rejeitou a release porque o gate ainda reconhecia apenas nomes de fases antigas e exigia declaração textual explícita sobre execução automática.

Correção única:
- adiciona `sem execucao automatica` ao FOCO do installer;
- ensina o Release Polish gate a reconhecer `CPU Vendor Deep Provider Foundation`;
- não altera capabilities, providers, rotas de hardware nem autonomia.


# Phoenix Forge 0.25.0rc1 — CPU Vendor Deep Provider Foundation

Base congelada: Phoenix Forge 0.24.0 (Windows verified).

Objetivo único: adicionar uma camada vendor-aware de CPU Deep para Intel e AMD sobre o contrato privilegiado read-only existente, sem aumentar autonomia.

- Novo `cpu_vendor_deep.py`.
- Intel e AMD são tratados como fornecedores de primeira classe.
- `cpu.intel.vendor_deep` e `cpu.amd.vendor_deep` ficam `RUNTIME_DEPENDENT`.
- Ausência de driver assinado não é falha de hardware.
- Nenhum driver vulnerável de terceiros é aceito.
- Nenhum valor MSR/CPPC/P-state/thermal é fabricado.
- API read-only `/api/hardware/cpu-vendor-deep` e `/capabilities`.
- CLI `phoenix-forge cpu-vendor-deep`.
- Decision Engine, automatic dispatch e automatic orchestration continuam desabilitados.


# Phoenix Forge 0.24.0 — Capability Completion Final

Final consolidation of Gates 24A–24D. No new hardware autonomy. Decision Engine remains blocked.

## 0.23.9 — Shadow Reliability Scorecard and Promotion Gates
- Registra base/shadow por execution_id e valida somente resultados realmente observados; counterfactual nao executado permanece unresolved.
- Decision Engine continua bloqueado; sem dispatch automatico.

# 0.20.8 — AHDE Evidence Bridge + Semantic Sensor Fusion

- Engine AHDE feeds normalized local sensor evidence into Forge every 5 seconds.
- Sensor Fusion v2 merges AHDE and Forge providers with provenance/confidence.
- Missing remains UNKNOWN; zero is not automatically missing; ambiguous power-zero is flagged.
- Adds `/api/evidence/ahde` and `/api/evidence/ahde/status`.

## 0.20.6
- Safe Provider Execution Runtime: chamadas read-only verificadas, protocolo JSON, circuit breaker e audit trail.

# Phoenix Forge changelog

## 0.19.8 — System Bottleneck & Configuration Auditor
- Evidence-only configuration findings and bottleneck claim contract.
- Setup Intelligence v2.
- Parity Matrix v7.
- System Report v12.

See versioned changelogs for prior releases.

## 0.20.2
- Telemetry Governance + Firestore Expansion: consentimento explícito, aviso/preview/revogação, sanitização de dados e fila de exportação.

## 0.20.4
Telemetry preview reliability, persistent GPU identity registry, safer VBIOS qualification UX and telemetry UI placement.


## 0.20.7
See CHANGELOG_0.20.7.md.


See CHANGELOG_0.21.0.md for Multi-Device Scheduler Foundation.

## 0.23.4.1
- Release Polish semantic gate fix: phase wording may evolve, safety invariants may not.


## 0.23.4.1
Runtime Observation Bridge: Phoenix Llama Runtime/Phoenix Diffusion evidence -> calibration journal, observation-only.
## Gate 2 RC2 — Windows UTF-8 BOM hardening
- `windows_evidence_promotion` now reads JSON using `utf-8-sig`, accepting both BOM and non-BOM UTF-8.
- Added regression coverage for PowerShell 5.1 `Set-Content -Encoding UTF8` run-context files and BOM-prefixed ledgers.
- Canonical release remains `0.25.0rc6.post15`; this is a repaired candidate, not a version advance.


## Gate 2 RC4 — Runtime Failure Interception + Architecture Fallback repair
- Fixed guarded-runtime circular JSON serialization and Forge 500 failure.
- Added failure classification/evidence and safe architecture fallback to CPU.
- Forge HTTP 5xx is treated as degradation; 4xx policy rejection remains fail-closed.
- Engine performs one CPU runtime recovery attempt and only accepts a real guarded completion.
- Fixed post15 smoke verification-overlay semantics.
- Canonical release remains 0.25.0rc6.post15.


## Gate 2 RC5 — Dynamic Verification Overlay Regression Fix
- Corrige `selftest_dynamic_verification_counts_0250rc6post8.py` para validar o estado efetivo Registry + Windows Evidence Overlay.
- Corrige o smoke do instalador para calcular `synthetic_verified` e `windows_verified` por capability ID após overlay, sem assumir `raw_synthetic - windows_count`.
- Mantém fail-closed, Gate 2 e versão canônica `0.25.0rc6.post15`.
- Nenhuma promoção de hardware é inferida.
