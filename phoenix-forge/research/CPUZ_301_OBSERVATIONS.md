# CPU-Z 3.01 — observações aplicadas à Phoenix Forge

## Amostra estudada

- Executável Windows x64 real, versão 3.0.1, com aproximadamente 7,4 MB.
- Recursos internos indicam drivers auxiliares x86, x64 e IA64.
- O driver x64 expõe operações privilegiadas relacionadas a memória física, portas de I/O e configuração PCI.
- A configuração observada habilita famílias de coleta como ACPI, PCI, DMI, sensores, SMBus, display, clock de barramento, chipset, SPD, LPCIO e SMART.

## Capacidades identificadas

- CPUID, família, modelo, stepping, topologia e classes de núcleo.
- Conjuntos de instrução e estado de suporte do sistema operacional.
- Hierarquia de cache.
- SPD/JEDEC/XMP via acesso privilegiado apropriado.
- Enumeração PCIe e integrações opcionais de GPU.

## Aplicação própria na Forge

Na v0.8, a Forge introduz inventário via CIM, sysfs/procfs e helper CPUID próprio. A estratégia é por provedores: a ausência de um provedor privilegiado deve aparecer como limitação, jamais ser preenchida por inferência. O código, driver e recursos do CPU-Z não são redistribuídos.

## Próxima maturação

Um provedor Phoenix assinado para Windows será necessário antes de oferecer SPD bruto, MSR, I/O e PCI configuration space. Isso exige projeto de segurança, privilégios mínimos, assinatura, telemetria de falha e testes em hardware real.
