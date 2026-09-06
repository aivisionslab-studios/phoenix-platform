# Condições de Uso — AIVisions Phoenix Engine

Este documento descreve, em termos operacionais, o que a Phoenix Engine pode fazer no seu sistema e sob quais condições.

## 1. Ações que a Phoenix pode executar (mediante autorização)

Ao autorizar uma instalação, missão ou fluxo de provisionamento, a Phoenix pode:

- Baixar modelos de IA de repositórios públicos (Hugging Face, catálogos oficiais AIVisionsLab, etc.);
- Instalar e configurar Docker, Python, drivers de GPU e dependências de sistema;
- Compilar software (ex.: llama.cpp, stable-diffusion.cpp) para o hardware detectado;
- Criar, atualizar e remover containers Docker;
- Utilizar recursos de CPU, GPU (incluindo VRAM), RAM e armazenamento local;
- Atualizar componentes da própria Phoenix e das tecnologias que orquestra;
- Consultar a internet para buscas (via SearXNG) quando o usuário solicitar.

Todas essas ações passam pelo fluxo do Resident Manager: **Intent → Research → Decision → Approval → Execute** — ou seja, ações potencialmente destrutivas ou que consomem recursos significativos aguardam aprovação explícita antes de serem executadas (ver [RESIDENT_MANAGER.md](../docs/RESIDENT_MANAGER.md)).

## 2. Usos pretendidos

A Phoenix foi desenvolvida para:

- ✅ Uso pessoal e doméstico
- ✅ Pesquisa e experimentação
- ✅ Desenvolvimento de software
- ✅ Educação e ensino de IA local
- ✅ Uso corporativo/empresarial, conforme a licença aplicável

## 3. Usos proibidos

Não é permitido utilizar a Phoenix para:

- ❌ Desenvolvimento de armas ou sistemas de dano físico
- ❌ Criação ou distribuição de malware
- ❌ Vigilância ilegal ou não consentida de terceiros
- ❌ Exploração ou abuso infantil, em qualquer forma
- ❌ Atividades terroristas ou de violência extremista
- ❌ Violação deliberada de direitos autorais ou licenças de terceiros
- ❌ Contornar controles de exportação ou sanções internacionais (ver [EXPORT_CONTROL.md](./EXPORT_CONTROL.md))

## 4. Consentimento e controle do usuário

A Phoenix não executa ações destrutivas ou irreversíveis sem aprovação explícita. O usuário mantém controle total sobre:

- Quais missões são aprovadas ou rejeitadas (comandos `aprovar`/`rejeitar`);
- Se a telemetria é compartilhada com o Firestore da AIVisionsLab (opt-in);
- Quais modelos e tecnologias são instalados.

## 5. Requisitos de hardware

Ver [HARDWARE.md](../docs/HARDWARE.md) para requisitos mínimos e recomendados. A Phoenix ajusta automaticamente sua estratégia de execução (CPU, GPU ou híbrida) conforme o hardware disponível, mas não garante desempenho específico em qualquer configuração.
