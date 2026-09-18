# Implementacao da Auditoria — Phoenix Forge 0.20.0

## Lacunas atacadas nesta release

| Lacuna da auditoria | Estado 0.20.0 | Implementacao |
|---|---|---|
| PCIe negotiated state/ReBAR | RUNTIME_DEPENDENT | Mantido/expandido via PCIe Link Intelligence 0.19.9 |
| NVMe / storage deep | RUNTIME_DEPENDENT | Windows Storage CIM + reliability counters |
| Sensores vendor profundos | PARTIAL/RUNTIME_DEPENDENT | Sensor Fusion preserva provider/proveniencia e UNKNOWN |
| SPD/SMBus live | PLANNED + CONTRACTED | Contrato privilegiado; sem valores falsos |
| APERF/MPERF / BCLK | PLANNED + CONTRACTED | Contrato MSR privilegiado; sem inferencia por CurrentMhz |
| Instrumentacao eletrica PSU | PLANNED + CONTRACTED | Contrato vendor/external sensor |
| Lacunas de auditoria | TRACKED | Audit Gap Tracker exposto por API |
| Interpretacao do setup | EXPANDED | Recommendation Engine baseado em evidencia |

## Regra de produto

O Forge nao deve buscar "100%" por maquiagem. Cada capacidade deve ser classificada como COMPLETE, RUNTIME_DEPENDENT ou PLANNED, e toda conclusao operacional deve carregar evidencia/proveniencia suficiente para ser auditavel.
