# Implementação da Auditoria — Phoenix Forge 0.19.9

Este release transforma itens concretos da auditoria 0.19.8 em estrutura executável.

## Implementado agora

### PCIe Link Intelligence
- provider Windows para propriedades PCIe atuais/máximas quando o SO/driver expõe os DEVPKEYs;
- geração atual/máxima;
- largura atual/máxima;
- largura de banda teórica por direção;
- BDF/root path reaproveitando Compute Fabric;
- ReBAR apenas por evidência explícita;
- classificação separada de `WIDTH_REDUCED` e `SPEED_BELOW_MAX`;
- geração reduzida em idle fica `NEEDS_LOAD_VALIDATION`, não `BOTTLENECK`.

### Integração sistêmica
- Hardware Inspector v4 incorpora a evidência PCIe;
- Configuration Auditor gera findings PCIe;
- Setup Intelligence incorpora PCIe Link Intelligence;
- System Report v13 inclui PCIe Link Intelligence;
- Parity Matrix v8 mede as novas capacidades;
- `/api/hardware/pcie-link`;
- `/api/capabilities`.

### Correção encontrada durante a injeção
`setup_intelligence.py` ainda procurava `parity["items"]`, mas a matriz atual usa `parity["capabilities"]`. O resumo DONE/PARTIAL/MISSING ficava zerado. O 0.19.9 corrige isso.

## Estrutura de lacunas orientada pela auditoria
O Capability Registry diferencia:
- `RUNTIME_DEPENDENT`: implementação existe, depende de hardware/provider/permissão;
- `PLANNED`: não é reivindicada como funcional;
- capacidade ausente nunca é promovida silenciosamente a DONE.

Lacunas preservadas explicitamente para próximos releases:
1. SPD/SMBus real + XMP/EXPO;
2. APERF/MPERF + BCLK/multiplicador via provider privilegiado;
3. sensor layer vendor profundo;
4. NVMe SMART/PCIe/endurance/thermal deep inspector;
5. scheduler multi-device SINGLE/COOPERATIVE/PARALLEL com NUMA-aware placement.

## Invariantes
- `device_key` é identidade persistente; `device_index` é seletor runtime.
- OOM/capacity não prova corrupção física.
- PCIe speed abaixo do máximo em idle não prova gargalo.
- afinidade desconhecida permanece UNKNOWN.
- ReBAR não é inferido por tamanho de VRAM.
- conflito entre providers permanece visível.
