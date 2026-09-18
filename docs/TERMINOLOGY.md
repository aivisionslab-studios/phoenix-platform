# PHOENIX ENGINE — Terminologia Oficial

| Termo | Definição |
| :--- | :--- |
| **Blueprint** | Um template declarativo (arquivo JSON). Define a receita de como montar um ambiente. |
| **Mission** | Uma instância de um Blueprint em tempo de execução. Possui estado. |
| **MissionStep** | Uma ação abstrata dentro de uma Missão. Não conhece o SO. |
| **ExecutionPlan** | A tradução concreta de um MissionStep para o Sistema Operacional. |
| **Capability** | Uma abstração de hardware/software (ex: `CAPABILITY_GPU_VULKAN`). |
| **Knowledge** | Informação persistente da máquina (hardware fixo, modelos baixados). |
| **State** | Snapshot instantâneo da máquina (Uso de CPU, Temperatura). |
| **Runtime** | Contexto da sessão atual (Usuário logado, permissões). |
| **Reasoning Engine**| O cérebro. Lê a Knowledge, interpreta a intenção. |
| **Provider** | Implementação específica de uma interface para um SO ou serviço. |
