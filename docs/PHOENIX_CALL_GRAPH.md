# PHOENIX CALL GRAPH

Documento gerado automaticamente via análise AST do código-fonte.

Nenhuma hipótese. Apenas fatos extraídos do parse do Python.

> **PHX-NOTE (varredura 2026-08-21 rodada 3)**: este documento ficou
> desatualizado em pelo menos um ponto confirmado — a seção
> `phoenix_kernel/runtime/drivers/sd_cpp.py` abaixo (por volta da linha
> 1130) lista `Importa: phoenix_kernel.runtime.pipeline.catalog_pipeline`,
> `phoenix_kernel.runtime.builders.registry` e
> `phoenix_kernel.runtime.executors.subprocess_executor`, mas o `sd_cpp.py`
> real hoje (confirmado lendo o arquivo e checando seus imports de verdade)
> NÃO importa nenhum desses três módulos — eles fazem parte de um
> subsistema (`runtime/pipeline/`, `runtime/builders/`, `runtime/executors/`,
> `runtime/contracts/`) que uma migração (`docs/phoenix_runtime_migration.py`)
> começou a preparar mas nunca terminou de conectar ao driver real. Ou seja:
> o "fato extraído do parse" descrito aqui não bate com o parse do arquivo
> atual — provavelmente este documento foi gerado numa versão anterior do
> código, antes do driver real ser desacoplado dessa migração inacabada.
> Não foi feita uma regeneração completa deste arquivo nesta rodada (o
> gerador em `tools/generate_phoenix_map.py` tem um `ROOT` hardcoded pra um
> caminho Windows de outra máquina e produz um arquivo de saída com nome
> diferente — não é claramente o mesmo gerador usado pra este documento);
> tratar como desatualizado além do ponto sinalizado acima até uma
> regeneração de verdade.


## 1. Arquivos Analisados

- `api_server.py`
- `generate_phoenix_map.py`
- `install_phoenix_kernel.py`
- `phoenix_models_migration.py`
- `phoenix_runtime_migration.py`
- `setup_environment.py`
- `setup_platform.py`
- `phoenix_kernel/cloud_sync.py`
- `phoenix_kernel/kernel.py`
- `phoenix_kernel/paths.py`
- `phoenix_kernel/state.py`
- `phoenix_kernel/__init__.py`
- `tests/test_mission_kernel.py`
- `tools/setup_firestore.py`
- `core/contracts/agent.py`
- `core/contracts/backup.py`
- `core/contracts/benchmark.py`
- `core/contracts/config.py`
- `core/contracts/connector.py`
- `core/contracts/engine.py`
- `core/contracts/experience.py`
- `core/contracts/gateway.py`
- `core/contracts/hardware.py`
- `core/contracts/installer.py`
- `core/contracts/knowledge.py`
- `core/contracts/mission.py`
- `core/contracts/model.py`
- `core/contracts/notification.py`
- `core/contracts/observability.py`
- `core/contracts/pipeline.py`
- `core/contracts/plugin.py`
- `core/contracts/rules.py`
- `core/contracts/runtime.py`
- `core/contracts/scheduler.py`
- `core/contracts/security.py`
- `core/contracts/storage.py`
- `core/contracts/updater.py`
- `core/contracts/workflow.py`
- `core/contracts/__init__.py`
- `core/domain/configuration.py`
- `core/domain/engine.py`
- `core/domain/execution.py`
- `core/domain/hardware.py`
- `core/domain/machine.py`
- `core/domain/models.py`
- `core/domain/provision.py`
- `core/domain/runtime.py`
- `core/domain/telemetry.py`
- `core/domain/workflows.py`
- `core/domain/__init__.py`
- `core/events/base.py`
- `core/events/bus.py`
- `core/events/types.py`
- `core/events/__init__.py`
- `core/kernel/kernel.py`
- `core/kernel/lifecycle.py`
- `core/kernel/plugin_base.py`
- `core/kernel/plugin_context.py`
- `core/kernel/plugin_loader.py`
- `core/kernel/registry.py`
- `core/kernel/__init__.py`
- `core/shared/logging.py`
- `core/shared/__init__.py`
- `phoenix_kernel/api/config.py`
- `phoenix_kernel/api/engine.py`
- `phoenix_kernel/api/exceptions.py`
- `phoenix_kernel/api/interfaces.py`
- `phoenix_kernel/api/models.py`
- `phoenix_kernel/api/__init__.py`
- `phoenix_kernel/budget/config.py`
- `phoenix_kernel/budget/engine.py`
- `phoenix_kernel/budget/exceptions.py`
- `phoenix_kernel/budget/interfaces.py`
- `phoenix_kernel/budget/models.py`
- `phoenix_kernel/budget/__init__.py`
- `phoenix_kernel/contracts/connector_contract.py`
- `phoenix_kernel/contracts/service_contract.py`
- `phoenix_kernel/contracts/__init__.py`
- `phoenix_kernel/core/enums.py`
- `phoenix_kernel/core/event_bus.py`
- `phoenix_kernel/core/exceptions.py`
- `phoenix_kernel/core/models.py`
- `phoenix_kernel/core/planner.py`
- `phoenix_kernel/core/__init__.py`
- `phoenix_kernel/dashboard/config.py`
- `phoenix_kernel/dashboard/engine.py`
- `phoenix_kernel/dashboard/exceptions.py`
- `phoenix_kernel/dashboard/interfaces.py`
- `phoenix_kernel/dashboard/models.py`
- `phoenix_kernel/dashboard/__init__.py`
- `phoenix_kernel/discovery/config.py`
- `phoenix_kernel/discovery/discovery_core.py`
- `phoenix_kernel/discovery/discovery_engine.py`
- `phoenix_kernel/discovery/engine.py`
- `phoenix_kernel/discovery/exceptions.py`
- `phoenix_kernel/discovery/interfaces.py`
- `phoenix_kernel/discovery/models.py`
- `phoenix_kernel/discovery/__init__.py`
- `phoenix_kernel/install/__init__.py`
- `phoenix_kernel/intelligence/interfaces.py`
- `phoenix_kernel/intelligence/knowledge_engine.py`
- `phoenix_kernel/intelligence/memory_loader.py`
- `phoenix_kernel/intelligence/reasoning_engine.py`
- `phoenix_kernel/intelligence/web_search.py`
- `phoenix_kernel/intelligence/__init__.py`
- `phoenix_kernel/models/config.py`
- `phoenix_kernel/models/engine.py`
- `phoenix_kernel/models/exceptions.py`
- `phoenix_kernel/models/interfaces.py`
- `phoenix_kernel/models/inventory.py`
- `phoenix_kernel/models/models.py`
- `phoenix_kernel/models/model_manager.py`
- `phoenix_kernel/models/model_scanner.py`
- `phoenix_kernel/models/__init__.py`
- `phoenix_kernel/planner/config.py`
- `phoenix_kernel/planner/engine.py`
- `phoenix_kernel/planner/evaluator.py`
- `phoenix_kernel/planner/exceptions.py`
- `phoenix_kernel/planner/interfaces.py`
- `phoenix_kernel/planner/knowledge_engine.py`
- `phoenix_kernel/planner/models.py`
- `phoenix_kernel/planner/__init__.py`
- `phoenix_kernel/resident/approval_engine.py`
- `phoenix_kernel/resident/decision_engine.py`
- `phoenix_kernel/resident/interfaces.py`
- `phoenix_kernel/resident/memory.py`
- `phoenix_kernel/resident/research_connector.py`
- `phoenix_kernel/resident/resident_manager.py`
- `phoenix_kernel/resident/tools.py`
- `phoenix_kernel/resident/__init__.py`
- `phoenix_kernel/runtime/config.py`
- `phoenix_kernel/runtime/engine.py`
- `phoenix_kernel/runtime/exceptions.py`
- `phoenix_kernel/runtime/interfaces.py`
- `phoenix_kernel/runtime/models.py`
- `phoenix_kernel/runtime/runtime_engine OLD.py`
- `phoenix_kernel/runtime/__init__.py`
- `phoenix_kernel/security/config.py`
- `phoenix_kernel/security/engine.py`
- `phoenix_kernel/security/exceptions.py`
- `phoenix_kernel/security/interfaces.py`
- `phoenix_kernel/security/models.py`
- `phoenix_kernel/security/__init__.py`
- `phoenix_kernel/services/catalog.py`
- `phoenix_kernel/services/config.py`
- `phoenix_kernel/services/engine.py`
- `phoenix_kernel/services/exceptions.py`
- `phoenix_kernel/services/install_target.py`
- `phoenix_kernel/services/interfaces.py`
- `phoenix_kernel/services/lmstudio_service.py`
- `phoenix_kernel/services/models.py`
- `phoenix_kernel/services/package_manager.py`
- `phoenix_kernel/services/platform_process.py`
- `phoenix_kernel/services/provisioning.py`
- `phoenix_kernel/services/__init__.py`
- `phoenix_kernel/shared/hardware_provider.py`
- `phoenix_kernel/shared/models.py`
- `phoenix_kernel/shared/storage.py`
- `phoenix_kernel/shared/__init__.py`
- `phoenix_kernel/telemetry/config.py`
- `phoenix_kernel/telemetry/core.py`
- `phoenix_kernel/telemetry/engine.py`
- `phoenix_kernel/telemetry/exceptions.py`
- `phoenix_kernel/telemetry/interfaces.py`
- `phoenix_kernel/telemetry/models.py`
- `phoenix_kernel/telemetry/__init__.py`
- `phoenix_kernel/validation/config.py`
- `phoenix_kernel/validation/engine.py`
- `phoenix_kernel/validation/exceptions.py`
- `phoenix_kernel/validation/interfaces.py`
- `phoenix_kernel/validation/models.py`
- `phoenix_kernel/validation/__init__.py`
- `phoenix_kernel/api/helpers/__init__.py`
- `phoenix_kernel/api/services/__init__.py`
- `phoenix_kernel/api/tests/__init__.py`
- `phoenix_kernel/budget/helpers/__init__.py`
- `phoenix_kernel/budget/services/__init__.py`
- `phoenix_kernel/budget/tests/__init__.py`
- `phoenix_kernel/dashboard/helpers/__init__.py`
- `phoenix_kernel/dashboard/services/__init__.py`
- `phoenix_kernel/dashboard/tests/__init__.py`
- `phoenix_kernel/discovery/helpers/__init__.py`
- `phoenix_kernel/discovery/providers/base.py`
- `phoenix_kernel/discovery/providers/factory.py`
- `phoenix_kernel/discovery/providers/linux.py`
- `phoenix_kernel/discovery/providers/windows.py`
- `phoenix_kernel/discovery/providers/__init__.py`
- `phoenix_kernel/discovery/services/__init__.py`
- `phoenix_kernel/discovery/tests/__init__.py`
- `phoenix_kernel/install/connectors/connectors.py`
- `phoenix_kernel/install/connectors/__init__.py`
- `phoenix_kernel/models/helpers/__init__.py`
- `phoenix_kernel/models/services/__init__.py`
- `phoenix_kernel/models/tests/__init__.py`
- `phoenix_kernel/planner/helpers/__init__.py`
- `phoenix_kernel/planner/services/__init__.py`
- `phoenix_kernel/planner/tests/__init__.py`
- `phoenix_kernel/rag/source_docs/audio_translation_script.py`
- `phoenix_kernel/runtime/builders/base_builder.py`
- `phoenix_kernel/runtime/builders/flux_builder.py`
- `phoenix_kernel/runtime/builders/registry.py`
- `phoenix_kernel/runtime/builders/sd15_builder.py`
- `phoenix_kernel/runtime/builders/__init__.py`
- `phoenix_kernel/runtime/contracts/model_contracts.py`
- `phoenix_kernel/runtime/contracts/__init__.py`
- `phoenix_kernel/runtime/drivers/comfyui.py`
- `phoenix_kernel/runtime/drivers/llama_cpp.py`
- `phoenix_kernel/runtime/drivers/ollama.py`
- `phoenix_kernel/runtime/drivers/piper.py`
- `phoenix_kernel/runtime/drivers/sd_cpp.py`
- `phoenix_kernel/runtime/drivers/whisper.py`
- `phoenix_kernel/runtime/executors/subprocess_executor.py`
- `phoenix_kernel/runtime/executors/__init__.py`
- `phoenix_kernel/runtime/helpers/__init__.py`
- `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
- `phoenix_kernel/runtime/pipeline/__init__.py`
- `phoenix_kernel/runtime/registry/__init__.py`
- `phoenix_kernel/runtime/services/__init__.py`
- `phoenix_kernel/runtime/tests/__init__.py`
- `phoenix_kernel/runtime/validators/__init__.py`
- `phoenix_kernel/security/helpers/__init__.py`
- `phoenix_kernel/security/services/__init__.py`
- `phoenix_kernel/security/tests/__init__.py`
- `phoenix_kernel/services/helpers/__init__.py`
- `phoenix_kernel/services/services/__init__.py`
- `phoenix_kernel/services/tests/__init__.py`
- `phoenix_kernel/telemetry/helpers/__init__.py`
- `phoenix_kernel/telemetry/providers/base.py`
- `phoenix_kernel/telemetry/providers/factory.py`
- `phoenix_kernel/telemetry/providers/linux.py`
- `phoenix_kernel/telemetry/providers/windows.py`
- `phoenix_kernel/telemetry/providers/__init__.py`
- `phoenix_kernel/telemetry/services/__init__.py`
- `phoenix_kernel/telemetry/tests/__init__.py`
- `phoenix_kernel/validation/helpers/__init__.py`
- `phoenix_kernel/validation/services/__init__.py`
- `phoenix_kernel/validation/tests/__init__.py`

---


## 2. Grafo de Imports

### `api_server.py`
  - Importa: `os`
  - Importa: `time`
  - Importa: `platform`
  - Importa: `threading`
  - Importa: `webbrowser`
  - Importa: `importlib`
  - Importa: `fastapi`
  - Importa: `fastapi.responses`
  - Importa: `pathlib`
  - Importa: `pydantic`
  - Importa: `phoenix_kernel.kernel`
  - Importa: `phoenix_kernel.cloud_sync`
  - Importa: `uvicorn`

### `generate_phoenix_map.py`
  - Importa: `pathlib`
  - Importa: `ast`
  - Importa: `datetime`

### `install_phoenix_kernel.py`
  - Importa: `__future__`
  - Importa: `argparse`
  - Importa: `pathlib`

### `phoenix_models_migration.py`
  - Importa: `json`
  - Importa: `os`
  - Importa: `shutil`
  - Importa: `hashlib`
  - Importa: `platform`
  - Importa: `pathlib`
  - Importa: `datetime`
  - Importa: `sys`
  - Importa: `phoenix_kernel.models.model_scanner`
  - Importa: `phoenix_kernel.paths`
  - Importa: `phoenix_kernel.models.inventory`

### `phoenix_runtime_migration.py`
  - Importa: `os`
  - Importa: `re`
  - Importa: `shutil`
  - Importa: `pathlib`
  - Importa: `datetime`

### `setup_environment.py`
  - Importa: `os`
  - Importa: `json`
  - Importa: `pathlib`

### `setup_platform.py`
  - Importa: `__future__`
  - Importa: `subprocess`
  - Importa: `sys`
  - Importa: `pathlib`

### `phoenix_kernel/cloud_sync.py`
  - Importa: `asyncio`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `os`
  - Importa: `socket`
  - Importa: `uuid`
  - Importa: `pathlib`
  - Importa: `phoenix_kernel.paths`
  - Importa: `google.cloud`
  - Importa: `google.oauth2`
  - Importa: `google.cloud`
  - Importa: `google.cloud`
  - Importa: `google.cloud`
  - Importa: `google.cloud`

### `phoenix_kernel/kernel.py`
  - Importa: `asyncio`
  - Importa: `importlib`
  - Importa: `logging`
  - Importa: `pathlib`
  - Importa: `core.events.bus`
  - Importa: `core.kernel.kernel`
  - Importa: `core.domain.machine`
  - Importa: `phoenix_kernel.state`
  - Importa: `phoenix_kernel.cloud_sync`
  - Importa: `setup_platform`
  - Importa: `core.domain.execution`
  - Importa: `phoenix_kernel.paths`

### `phoenix_kernel/paths.py`
  - Importa: `__future__`
  - Importa: `json`
  - Importa: `platform`
  - Importa: `pathlib`

### `phoenix_kernel/state.py`
  - Importa: `asyncio`
  - Importa: `logging`

### `tests/test_mission_kernel.py`
  - Importa: `pytest`
  - Importa: `phoenix_kernel.core.models`
  - Importa: `phoenix_kernel.core.enums`
  - Importa: `phoenix_kernel.core.planner`
  - Importa: `phoenix_kernel.core.kernel`
  - Importa: `phoenix_kernel.core.exceptions`

### `tools/setup_firestore.py`
  - Importa: `pathlib`
  - Importa: `json`
  - Importa: `platform`
  - Importa: `socket`
  - Importa: `uuid`
  - Importa: `google.cloud`
  - Importa: `google.oauth2`

### `core/contracts/agent.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/backup.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/benchmark.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/config.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/connector.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/engine.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.engine`

### `core/contracts/experience.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/gateway.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/hardware.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.machine`
  - Importa: `core.domain.telemetry`
  - Importa: `core.domain.hardware`

### `core/contracts/installer.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.execution`

### `core/contracts/knowledge.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/mission.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.workflows`

### `core/contracts/model.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.models`

### `core/contracts/notification.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/observability.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/pipeline.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.workflows`

### `core/contracts/plugin.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/rules.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.machine`
  - Importa: `core.domain.execution`

### `core/contracts/runtime.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`

### `core/contracts/scheduler.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/security.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/storage.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `pathlib`

### `core/contracts/updater.py`
  - Importa: `__future__`
  - Importa: `typing`

### `core/contracts/workflow.py`
  - Importa: `__future__`
  - Importa: `typing`
  - Importa: `core.domain.workflows`

### `core/contracts/__init__.py`
  - Importa: `engine`
  - Importa: `hardware`
  - Importa: `runtime`
  - Importa: `rules`
  - Importa: `installer`
  - Importa: `connector`
  - Importa: `model`
  - Importa: `workflow`
  - Importa: `knowledge`
  - Importa: `agent`
  - Importa: `mission`
  - Importa: `security`
  - Importa: `observability`
  - Importa: `storage`
  - Importa: `benchmark`
  - Importa: `gateway`
  - Importa: `pipeline`
  - Importa: `notification`
  - Importa: `scheduler`
  - Importa: `backup`
  - Importa: `updater`
  - Importa: `plugin`
  - Importa: `config`
  - Importa: `experience`

### `core/domain/configuration.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `typing`

### `core/domain/engine.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `enum`
  - Importa: `uuid`

### `core/domain/execution.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `enum`
  - Importa: `typing`
  - Importa: `uuid`

### `core/domain/hardware.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `typing`

### `core/domain/machine.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `typing`
  - Importa: `hashlib`

### `core/domain/models.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `pathlib`

### `core/domain/provision.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `typing`

### `core/domain/runtime.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `enum`
  - Importa: `typing`

### `core/domain/telemetry.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `typing`

### `core/domain/workflows.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `enum`
  - Importa: `typing`
  - Importa: `uuid`

### `core/events/base.py`
  - Importa: `__future__`
  - Importa: `dataclasses`
  - Importa: `datetime`
  - Importa: `typing`
  - Importa: `uuid`

### `core/events/bus.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `collections`
  - Importa: `typing`
  - Importa: `base`

### `core/events/__init__.py`
  - Importa: `base`
  - Importa: `bus`

### `core/kernel/kernel.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `core.contracts.engine`
  - Importa: `core.domain.engine`
  - Importa: `core.events.bus`
  - Importa: `registry`
  - Importa: `lifecycle`

### `core/kernel/lifecycle.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `core.contracts.engine`
  - Importa: `core.domain.engine`
  - Importa: `registry`

### `core/kernel/plugin_base.py`
  - Importa: `__future__`
  - Importa: `abc`
  - Importa: `core.kernel.plugin_context`

### `core/kernel/plugin_context.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `core.events.bus`
  - Importa: `core.kernel.registry`

### `core/kernel/plugin_loader.py`
  - Importa: `__future__`
  - Importa: `importlib.util`
  - Importa: `logging`
  - Importa: `pathlib`
  - Importa: `core.kernel.kernel`
  - Importa: `sys`

### `core/kernel/registry.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `core.contracts.engine`
  - Importa: `core.domain.engine`

### `core/kernel/__init__.py`
  - Importa: `kernel`
  - Importa: `registry`
  - Importa: `lifecycle`

### `core/shared/logging.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `pathlib`

### `phoenix_kernel/api/engine.py`
  - Importa: `logging`
  - Importa: `interfaces`
  - Importa: `phoenix_kernel.intelligence.web_search`

### `phoenix_kernel/api/interfaces.py`
  - Importa: `abc`

### `phoenix_kernel/budget/engine.py`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `interfaces`

### `phoenix_kernel/budget/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/contracts/connector_contract.py`
  - Importa: `abc`

### `phoenix_kernel/contracts/service_contract.py`
  - Importa: `abc`

### `phoenix_kernel/core/enums.py`
  - Importa: `enum`

### `phoenix_kernel/core/event_bus.py`
  - Importa: `logging`
  - Importa: `collections`

### `phoenix_kernel/core/models.py`
  - Importa: `dataclasses`
  - Importa: `typing`
  - Importa: `datetime`
  - Importa: `uuid`
  - Importa: `enums`

### `phoenix_kernel/core/planner.py`
  - Importa: `logging`
  - Importa: `models`
  - Importa: `enums`

### `phoenix_kernel/dashboard/engine.py`
  - Importa: `interfaces`

### `phoenix_kernel/dashboard/interfaces.py`
  - Importa: `abc`

### `phoenix_kernel/discovery/discovery_core.py`
  - Importa: `psutil`
  - Importa: `platform`
  - Importa: `hashlib`
  - Importa: `shutil`
  - Importa: `subprocess`
  - Importa: `re`
  - Importa: `os`
  - Importa: `tempfile`
  - Importa: `time`
  - Importa: `dataclasses`
  - Importa: `typing`
  - Importa: `json`
  - Importa: `json`
  - Importa: `dataclasses`
  - Importa: `wmi`
  - Importa: `wmi`
  - Importa: `json`

### `phoenix_kernel/discovery/discovery_engine.py`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `interfaces`
  - Importa: `discovery_core`

### `phoenix_kernel/discovery/engine.py`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `platform`
  - Importa: `typing`
  - Importa: `interfaces`
  - Importa: `providers.factory`

### `phoenix_kernel/discovery/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/intelligence/interfaces.py`
  - Importa: `abc`

### `phoenix_kernel/intelligence/knowledge_engine.py`
  - Importa: `__future__`
  - Importa: `json`
  - Importa: `pathlib`
  - Importa: `typing`
  - Importa: `memory_loader`
  - Importa: `memory_loader`

### `phoenix_kernel/intelligence/memory_loader.py`
  - Importa: `__future__`
  - Importa: `json`
  - Importa: `re`
  - Importa: `dataclasses`
  - Importa: `pathlib`
  - Importa: `typing`

### `phoenix_kernel/intelligence/reasoning_engine.py`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `asyncio`
  - Importa: `phoenix_kernel.core.models`
  - Importa: `phoenix_kernel.core.enums`
  - Importa: `phoenix_kernel.intelligence.web_search`
  - Importa: `phoenix_kernel.intelligence.knowledge_engine`
  - Importa: `core.domain.execution`

### `phoenix_kernel/intelligence/web_search.py`
  - Importa: `logging`
  - Importa: `httpx`

### `phoenix_kernel/models/engine.py`
  - Importa: `asyncio`
  - Importa: `urllib.request`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `interfaces`

### `phoenix_kernel/models/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/models/inventory.py`
  - Importa: `__future__`
  - Importa: `json`
  - Importa: `pathlib`
  - Importa: `datetime`
  - Importa: `phoenix_kernel.paths`
  - Importa: `phoenix_kernel.models.model_scanner`

### `phoenix_kernel/models/model_manager.py`
  - Importa: `os`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `asyncio`
  - Importa: `httpx`
  - Importa: `pathlib`
  - Importa: `phoenix_kernel.paths`

### `phoenix_kernel/models/model_scanner.py`
  - Importa: `__future__`
  - Importa: `hashlib`
  - Importa: `pathlib`
  - Importa: `datetime`
  - Importa: `phoenix_kernel.paths`

### `phoenix_kernel/planner/engine.py`
  - Importa: `logging`
  - Importa: `core.domain.machine`
  - Importa: `core.domain.execution`
  - Importa: `interfaces`
  - Importa: `knowledge_engine`
  - Importa: `evaluator`

### `phoenix_kernel/planner/evaluator.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `re`
  - Importa: `core.domain.machine`
  - Importa: `core.domain.execution`

### `phoenix_kernel/planner/interfaces.py`
  - Importa: `abc`
  - Importa: `core.domain.machine`
  - Importa: `core.domain.execution`

### `phoenix_kernel/planner/knowledge_engine.py`
  - Importa: `__future__`
  - Importa: `json`
  - Importa: `pathlib`
  - Importa: `typing`
  - Importa: `phoenix_kernel.intelligence.memory_loader`
  - Importa: `intelligence.memory_loader`

### `phoenix_kernel/resident/approval_engine.py`
  - Importa: `logging`

### `phoenix_kernel/resident/decision_engine.py`
  - Importa: `logging`

### `phoenix_kernel/resident/interfaces.py`
  - Importa: `abc`

### `phoenix_kernel/resident/memory.py`
  - Importa: `json`
  - Importa: `pathlib`

### `phoenix_kernel/resident/research_connector.py`
  - Importa: `logging`
  - Importa: `asyncio`

### `phoenix_kernel/resident/resident_manager.py`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `importlib`
  - Importa: `re`
  - Importa: `time`
  - Importa: `datetime`
  - Importa: `interfaces`
  - Importa: `phoenix_kernel.intelligence.reasoning_engine`
  - Importa: `phoenix_kernel.core.enums`
  - Importa: `core.domain.execution`

### `phoenix_kernel/runtime/engine.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `inspect`
  - Importa: `logging`
  - Importa: `pathlib`
  - Importa: `typing`
  - Importa: `core.contracts.engine`
  - Importa: `core.contracts.runtime`
  - Importa: `core.domain.engine`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`
  - Importa: `core.events.bus`
  - Importa: `core.events.base`
  - Importa: `core.kernel.kernel`
  - Importa: `drivers.llama_cpp`
  - Importa: `drivers.sd_cpp`
  - Importa: `drivers.whisper`
  - Importa: `drivers.piper`
  - Importa: `drivers.comfyui`

### `phoenix_kernel/runtime/interfaces.py`
  - Importa: `abc`
  - Importa: `core.domain.execution`

### `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `inspect`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `core.contracts.engine`
  - Importa: `core.contracts.runtime`
  - Importa: `core.domain.engine`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`
  - Importa: `core.events.bus`
  - Importa: `core.events.base`
  - Importa: `core.kernel.kernel`
  - Importa: `drivers.ollama`
  - Importa: `drivers.llama_cpp`
  - Importa: `drivers.sd_cpp`
  - Importa: `drivers.whisper`
  - Importa: `drivers.piper`
  - Importa: `drivers.comfyui`
  - Importa: `pathlib`

### `phoenix_kernel/security/engine.py`
  - Importa: `os`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `interfaces`
  - Importa: `ctypes`

### `phoenix_kernel/security/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/services/catalog.py`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `pathlib`

### `phoenix_kernel/services/engine.py`
  - Importa: `asyncio`
  - Importa: `shutil`
  - Importa: `urllib.request`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `pathlib`
  - Importa: `typing`
  - Importa: `interfaces`
  - Importa: `provisioning`
  - Importa: `package_manager`

### `phoenix_kernel/services/install_target.py`
  - Importa: `os`
  - Importa: `psutil`
  - Importa: `subprocess`
  - Importa: `logging`
  - Importa: `json`

### `phoenix_kernel/services/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/services/lmstudio_service.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `sys`
  - Importa: `httpx`
  - Importa: `subprocess`

### `phoenix_kernel/services/package_manager.py`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `asyncio`
  - Importa: `pathlib`
  - Importa: `provisioning`
  - Importa: `catalog`

### `phoenix_kernel/services/platform_process.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `os`
  - Importa: `sys`
  - Importa: `pathlib`

### `phoenix_kernel/services/provisioning.py`
  - Importa: `os`
  - Importa: `subprocess`
  - Importa: `urllib.request`
  - Importa: `logging`
  - Importa: `sys`
  - Importa: `pathlib`
  - Importa: `catalog`

### `phoenix_kernel/shared/hardware_provider.py`
  - Importa: `platform`
  - Importa: `subprocess`
  - Importa: `logging`
  - Importa: `clr`
  - Importa: `HardwareMonitor.Hardware`

### `phoenix_kernel/shared/models.py`
  - Importa: `dataclasses`
  - Importa: `typing`

### `phoenix_kernel/shared/storage.py`
  - Importa: `os`
  - Importa: `json`
  - Importa: `logging`
  - Importa: `pathlib`

### `phoenix_kernel/telemetry/core.py`
  - Importa: `logging`
  - Importa: `threading`
  - Importa: `platform`
  - Importa: `os`
  - Importa: `glob`
  - Importa: `json`
  - Importa: `re`
  - Importa: `subprocess`
  - Importa: `clr`
  - Importa: `HardwareMonitor.Hardware`

### `phoenix_kernel/telemetry/engine.py`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `psutil`
  - Importa: `typing`
  - Importa: `interfaces`
  - Importa: `providers.factory`

### `phoenix_kernel/telemetry/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/validation/engine.py`
  - Importa: `asyncio`
  - Importa: `psutil`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `interfaces`

### `phoenix_kernel/validation/interfaces.py`
  - Importa: `abc`
  - Importa: `typing`

### `phoenix_kernel/discovery/providers/base.py`
  - Importa: `abc`
  - Importa: `phoenix_kernel.shared.models`

### `phoenix_kernel/discovery/providers/factory.py`
  - Importa: `platform`
  - Importa: `windows`
  - Importa: `linux`

### `phoenix_kernel/discovery/providers/linux.py`
  - Importa: `glob`
  - Importa: `os`
  - Importa: `re`
  - Importa: `json`
  - Importa: `shutil`
  - Importa: `subprocess`
  - Importa: `logging`
  - Importa: `base`
  - Importa: `phoenix_kernel.shared.models`
  - Importa: `psutil`
  - Importa: `psutil`

### `phoenix_kernel/discovery/providers/windows.py`
  - Importa: `os`
  - Importa: `shutil`
  - Importa: `logging`
  - Importa: `platform`
  - Importa: `base`
  - Importa: `phoenix_kernel.shared.models`
  - Importa: `wmi`
  - Importa: `psutil`
  - Importa: `importlib`
  - Importa: `wmi`

### `phoenix_kernel/install/connectors/connectors.py`
  - Importa: `subprocess`
  - Importa: `urllib.request`
  - Importa: `logging`

### `phoenix_kernel/rag/source_docs/audio_translation_script.py`
  - Importa: `deep_translator`

### `phoenix_kernel/runtime/builders/base_builder.py`
  - Importa: `abc`
  - Importa: `typing`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`

### `phoenix_kernel/runtime/builders/flux_builder.py`
  - Importa: `typing`
  - Importa: `base_builder`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`

### `phoenix_kernel/runtime/builders/registry.py`
  - Importa: `typing`
  - Importa: `base_builder`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`
  - Importa: `flux_builder`
  - Importa: `sd15_builder`

### `phoenix_kernel/runtime/builders/sd15_builder.py`
  - Importa: `typing`
  - Importa: `base_builder`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`

### `phoenix_kernel/runtime/contracts/model_contracts.py`
  - Importa: `enum`
  - Importa: `dataclasses`
  - Importa: `pathlib`
  - Importa: `typing`

### `phoenix_kernel/runtime/drivers/comfyui.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`

### `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `json`
  - Importa: `os`
  - Importa: `httpx`
  - Importa: `pathlib`
  - Importa: `datetime`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`
  - Importa: `phoenix_kernel.paths`
  - Importa: `shutil`

### `phoenix_kernel/runtime/drivers/ollama.py`
  - Importa: `__future__`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `urllib.request`
  - Importa: `json`
  - Importa: `datetime`
  - Importa: `typing`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`
  - Importa: `base64`
  - Importa: `pathlib`

### `phoenix_kernel/runtime/drivers/piper.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `pathlib`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`

### `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `platform`
  - Importa: `pathlib`
  - Importa: `datetime`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`
  - Importa: `phoenix_kernel.runtime.pipeline.catalog_pipeline`
  - Importa: `phoenix_kernel.runtime.builders.registry`
  - Importa: `phoenix_kernel.runtime.executors.subprocess_executor`
  - Importa: `phoenix_kernel.paths`
  - Importa: `phoenix_kernel.paths`

### `phoenix_kernel/runtime/drivers/whisper.py`
  - Importa: `__future__`
  - Importa: `logging`
  - Importa: `pathlib`
  - Importa: `core.domain.execution`
  - Importa: `core.domain.runtime`

### `phoenix_kernel/runtime/executors/subprocess_executor.py`
  - Importa: `asyncio`
  - Importa: `logging`
  - Importa: `typing`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`

### `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Importa: `json`
  - Importa: `pathlib`
  - Importa: `phoenix_kernel.runtime.contracts.model_contracts`

### `phoenix_kernel/telemetry/providers/base.py`
  - Importa: `abc`
  - Importa: `phoenix_kernel.shared.models`

### `phoenix_kernel/telemetry/providers/factory.py`
  - Importa: `platform`
  - Importa: `windows`
  - Importa: `linux`

### `phoenix_kernel/telemetry/providers/linux.py`
  - Importa: `psutil`
  - Importa: `base`
  - Importa: `phoenix_kernel.shared.models`
  - Importa: `core`

### `phoenix_kernel/telemetry/providers/windows.py`
  - Importa: `psutil`
  - Importa: `base`
  - Importa: `phoenix_kernel.shared.models`
  - Importa: `core`


---


## 3. Classes e Herança

### `api_server.py`
  - Classe: `CommandRequest`
  - Classe: `InstallReq`

### `phoenix_kernel/cloud_sync.py`
  - Classe: `FirestoreSync`

### `phoenix_kernel/kernel.py`
  - Classe: `PhoenixKernel`
  - Classe: `Profile`

### `phoenix_kernel/paths.py`
  - Classe: `PhoenixPaths`

### `phoenix_kernel/state.py`
  - Classe: `StateEngine`

### `core/contracts/agent.py`
  - Classe: `IAgentSDK`

### `core/contracts/backup.py`
  - Classe: `IBackupSDK`

### `core/contracts/benchmark.py`
  - Classe: `IBenchmarkSDK`

### `core/contracts/config.py`
  - Classe: `IConfigurationSDK`

### `core/contracts/connector.py`
  - Classe: `IConnectorSDK`

### `core/contracts/engine.py`
  - Classe: `IEngine`

### `core/contracts/experience.py`
  - Classe: `IExperienceSDK`

### `core/contracts/gateway.py`
  - Classe: `IGatewaySDK`

### `core/contracts/hardware.py`
  - Classe: `IHardwareSDK`

### `core/contracts/installer.py`
  - Classe: `IInstallerSDK`

### `core/contracts/knowledge.py`
  - Classe: `IKnowledgeSDK`

### `core/contracts/mission.py`
  - Classe: `IMissionSDK`

### `core/contracts/model.py`
  - Classe: `IModelSDK`

### `core/contracts/notification.py`
  - Classe: `INotificationSDK`

### `core/contracts/observability.py`
  - Classe: `IObservabilitySDK`

### `core/contracts/pipeline.py`
  - Classe: `IPipelineSDK`

### `core/contracts/plugin.py`
  - Classe: `IPluginManagerSDK`

### `core/contracts/rules.py`
  - Classe: `IRulesSDK`

### `core/contracts/runtime.py`
  - Classe: `IRuntimeSDK`

### `core/contracts/scheduler.py`
  - Classe: `ISchedulerSDK`

### `core/contracts/security.py`
  - Classe: `ISecuritySDK`

### `core/contracts/storage.py`
  - Classe: `IStorageSDK`

### `core/contracts/updater.py`
  - Classe: `IUpdaterSDK`

### `core/contracts/workflow.py`
  - Classe: `IWorkflowSDK`

### `core/domain/configuration.py`
  - Classe: `UserPreferences`
  - Classe: `Policies`

### `core/domain/engine.py`
  - Classe: `HealthStatus`
  - Classe: `Capability`
  - Classe: `EngineDescriptor`

### `core/domain/execution.py`
  - Classe: `ExecutionStatus`
  - Classe: `ExecutionPlan`
  - Classe: `ExecutionResult`

### `core/domain/hardware.py`
  - Classe: `HardwareDescriptor`
  - Classe: `HardwareEvent`

### `core/domain/machine.py`
  - Classe: `MachineDNA`
  - Classe: `MachineProfile`
  - Classe: `MachineContext`

### `core/domain/models.py`
  - Classe: `ModelDescriptor`
  - Classe: `InstalledModel`

### `core/domain/provision.py`
  - Classe: `ProvisionItem`
  - Classe: `ProvisionPlan`

### `core/domain/runtime.py`
  - Classe: `RuntimeState`
  - Classe: `RuntimeDescriptor`
  - Classe: `RuntimeStatus`

### `core/domain/telemetry.py`
  - Classe: `TelemetrySample`
  - Classe: `TelemetrySnapshot`

### `core/domain/workflows.py`
  - Classe: `TaskStatus`
  - Classe: `Task`
  - Classe: `Workflow`
  - Classe: `Mission`

### `core/events/base.py`
  - Classe: `Event`
  - Classe: `Command`

### `core/events/bus.py`
  - Classe: `EventBus`

### `core/kernel/kernel.py`
  - Classe: `PlatformKernel`

### `core/kernel/lifecycle.py`
  - Classe: `LifecycleManager`

### `core/kernel/plugin_base.py`
  - Classe: `AIVisionsPlugin`

### `core/kernel/plugin_context.py`
  - Classe: `PluginContext`

### `core/kernel/registry.py`
  - Classe: `ServiceRegistry`

### `phoenix_kernel/api/engine.py`
  - Classe: `ApiEngine`

### `phoenix_kernel/api/interfaces.py`
  - Classe: `IApiService`

### `phoenix_kernel/budget/engine.py`
  - Classe: `BudgetEngine`

### `phoenix_kernel/budget/interfaces.py`
  - Classe: `IBudgetService`

### `phoenix_kernel/contracts/connector_contract.py`
  - Classe: `IConnector`

### `phoenix_kernel/contracts/service_contract.py`
  - Classe: `IService`

### `phoenix_kernel/core/enums.py`
  - Classe: `MissionAction`
  - Classe: `MissionStatus`

### `phoenix_kernel/core/event_bus.py`
  - Classe: `EventBus`

### `phoenix_kernel/core/exceptions.py`
  - Classe: `MissionError`
  - Classe: `NoActiveMissionError`

### `phoenix_kernel/core/models.py`
  - Classe: `MissionStep`
  - Classe: `Mission`

### `phoenix_kernel/core/planner.py`
  - Classe: `MissionPlanner`

### `phoenix_kernel/dashboard/engine.py`
  - Classe: `Engine`

### `phoenix_kernel/dashboard/interfaces.py`
  - Classe: `IEngine`

### `phoenix_kernel/discovery/discovery_core.py`
  - Classe: `CPUInfo`
  - Classe: `GPUInfo`
  - Classe: `MemoryInfo`
  - Classe: `StorageDeviceInfo`
  - Classe: `HardwareSnapshot`
  - Classe: `MachineIdentity`
  - Classe: `HardwareDiscoveryCore`

### `phoenix_kernel/discovery/discovery_engine.py`
  - Classe: `DiscoveryEngine`

### `phoenix_kernel/discovery/engine.py`
  - Classe: `DiscoveryEngine`

### `phoenix_kernel/discovery/interfaces.py`
  - Classe: `IDiscoveryService`

### `phoenix_kernel/intelligence/interfaces.py`
  - Classe: `IResidentManager`

### `phoenix_kernel/intelligence/knowledge_engine.py`
  - Classe: `RagBackend`
  - Classe: `KnowledgeEngine`

### `phoenix_kernel/intelligence/memory_loader.py`
  - Classe: `MemoryCard`
  - Classe: `MemoryLoader`

### `phoenix_kernel/intelligence/reasoning_engine.py`
  - Classe: `ReasoningEngine`

### `phoenix_kernel/models/engine.py`
  - Classe: `ModelsEngine`

### `phoenix_kernel/models/interfaces.py`
  - Classe: `IModelsService`

### `phoenix_kernel/models/inventory.py`
  - Classe: `ModelInventory`

### `phoenix_kernel/models/model_manager.py`
  - Classe: `ModelManager`

### `phoenix_kernel/models/model_scanner.py`
  - Classe: `ModelScanner`

### `phoenix_kernel/planner/engine.py`
  - Classe: `PlannerEngine`

### `phoenix_kernel/planner/evaluator.py`
  - Classe: `RuleEvaluator`

### `phoenix_kernel/planner/interfaces.py`
  - Classe: `IPlannerService`

### `phoenix_kernel/planner/knowledge_engine.py`
  - Classe: `RagBackend`
  - Classe: `KnowledgeEngine`

### `phoenix_kernel/resident/approval_engine.py`
  - Classe: `ApprovalEngine`

### `phoenix_kernel/resident/decision_engine.py`
  - Classe: `DecisionEngine`

### `phoenix_kernel/resident/interfaces.py`
  - Classe: `IResidentManager`

### `phoenix_kernel/resident/memory.py`
  - Classe: `ResidentMemory`

### `phoenix_kernel/resident/research_connector.py`
  - Classe: `ResearchConnector`

### `phoenix_kernel/resident/resident_manager.py`
  - Classe: `ResidentManager`

### `phoenix_kernel/runtime/engine.py`
  - Classe: `RuntimeEngine`

### `phoenix_kernel/runtime/interfaces.py`
  - Classe: `IRuntimeService`

### `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Classe: `RuntimeEngine`

### `phoenix_kernel/security/engine.py`
  - Classe: `SecurityEngine`

### `phoenix_kernel/security/interfaces.py`
  - Classe: `ISecurityService`

### `phoenix_kernel/services/catalog.py`
  - Classe: `CatalogEngine`

### `phoenix_kernel/services/engine.py`
  - Classe: `ServicesEngine`

### `phoenix_kernel/services/install_target.py`
  - Classe: `InstallTargetSelector`

### `phoenix_kernel/services/interfaces.py`
  - Classe: `IServicesService`

### `phoenix_kernel/services/package_manager.py`
  - Classe: `PackageManager`

### `phoenix_kernel/services/provisioning.py`
  - Classe: `ProvisioningManager`

### `phoenix_kernel/shared/models.py`
  - Classe: `CPUInfo`
  - Classe: `GPUInfo`
  - Classe: `MemoryInfo`
  - Classe: `StorageInfo`
  - Classe: `MotherboardInfo`
  - Classe: `HardwareSnapshot`
  - Classe: `TelemetrySnapshot`

### `phoenix_kernel/shared/storage.py`
  - Classe: `StorageManager`

### `phoenix_kernel/telemetry/engine.py`
  - Classe: `TelemetryEngine`

### `phoenix_kernel/telemetry/interfaces.py`
  - Classe: `ITelemetryService`

### `phoenix_kernel/validation/engine.py`
  - Classe: `ValidationEngine`

### `phoenix_kernel/validation/interfaces.py`
  - Classe: `IValidationService`

### `phoenix_kernel/discovery/providers/base.py`
  - Classe: `IDiscoveryProvider`

### `phoenix_kernel/discovery/providers/linux.py`
  - Classe: `LinuxDiscoveryProvider`

### `phoenix_kernel/discovery/providers/windows.py`
  - Classe: `WindowsDiscoveryProvider`

### `phoenix_kernel/install/connectors/connectors.py`
  - Classe: `WingetConnector`
  - Classe: `DockerConnector`
  - Classe: `GitConnector`

### `phoenix_kernel/runtime/builders/base_builder.py`
  - Classe: `ICommandBuilder`

### `phoenix_kernel/runtime/builders/flux_builder.py`
  - Classe: `FluxBuilder`

### `phoenix_kernel/runtime/builders/registry.py`
  - Classe: `BuilderRegistry`

### `phoenix_kernel/runtime/builders/sd15_builder.py`
  - Classe: `SD15Builder`

### `phoenix_kernel/runtime/contracts/model_contracts.py`
  - Classe: `ModelArchitecture`
  - Classe: `GenerationProfile`
  - Classe: `ModelDescriptor`
  - Classe: `RuntimeCapabilities`
  - Classe: `PhoenixRuntimeError`
  - Classe: `ExecutableNotFound`
  - Classe: `ModelNotFound`
  - Classe: `MissingComponent`
  - Classe: `BuilderNotSupported`
  - Classe: `GenerationFailed`
  - Classe: `CatalogInconsistency`

### `phoenix_kernel/runtime/drivers/comfyui.py`
  - Classe: `ComfyUIDriver`

### `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Classe: `LlamaCppDriver`

### `phoenix_kernel/runtime/drivers/ollama.py`
  - Classe: `OllamaDriver`

### `phoenix_kernel/runtime/drivers/piper.py`
  - Classe: `PiperDriver`

### `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Classe: `SdCppDriver`

### `phoenix_kernel/runtime/drivers/whisper.py`
  - Classe: `WhisperDriver`

### `phoenix_kernel/runtime/executors/subprocess_executor.py`
  - Classe: `SubprocessExecutor`

### `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Classe: `CatalogLoader`
  - Classe: `CatalogValidator`
  - Classe: `PathResolver`
  - Classe: `FileValidator`

### `phoenix_kernel/telemetry/providers/base.py`
  - Classe: `ITelemetryProvider`

### `phoenix_kernel/telemetry/providers/linux.py`
  - Classe: `LinuxTelemetryProvider`

### `phoenix_kernel/telemetry/providers/windows.py`
  - Classe: `WindowsTelemetryProvider`


---


## 4. Código Morto (Símbolos definidos mas nunca chamados no projeto)

- `AIVisionsPlugin`
- `ApprovalEngine`
- `BuilderRegistry`
- `CatalogLoader`
- `CatalogValidator`
- `Command`
- `CommandRequest`
- `DecisionEngine`
- `DockerConnector`
- `Engine`
- `ExecutionStatus`
- `FileValidator`
- `FluxBuilder`
- `GitConnector`
- `HardwareDescriptor`
- `HardwareEvent`
- `HealthStatus`
- `IAgentSDK`
- `IApiService`
- `IBackupSDK`
- `IBenchmarkSDK`
- `IBudgetService`
- `ICommandBuilder`
- `IConfigurationSDK`
- `IConnector`
- `IConnectorSDK`
- `IDiscoveryProvider`
- `IDiscoveryService`
- `IEngine`
- `IExperienceSDK`
- `IGatewaySDK`
- `IHardwareSDK`
- `IInstallerSDK`
- `IKnowledgeSDK`
- `IMissionSDK`
- `IModelSDK`
- `IModelsService`
- `INotificationSDK`
- `IObservabilitySDK`
- `IPipelineSDK`
- `IPlannerService`
- `IPluginManagerSDK`
- `IResidentManager`
- `IRulesSDK`
- `IRuntimeSDK`
- `IRuntimeService`
- `ISchedulerSDK`
- `ISecuritySDK`
- `ISecurityService`
- `IService`
- `IServicesService`
- `IStorageSDK`
- `ITelemetryProvider`
- `ITelemetryService`
- `IUpdaterSDK`
- `IValidationService`
- `IWorkflowSDK`
- `InstallReq`
- `InstallTargetSelector`
- `InstalledModel`
- `MachineDNA`
- `MachineProfile`
- `MissionError`
- `MissionStatus`
- `ModelInventory`
- `ModelScanner`
- `NoActiveMissionError`
- `PathResolver`
- `PhoenixPaths`
- `PhoenixRuntimeError`
- `PluginContext`
- `Policies`
- `ProvisionItem`
- `ProvisionPlan`
- `RagBackend`
- `ResearchConnector`
- `ResidentMemory`
- `RuntimeState`
- `SD15Builder`
- `SubprocessExecutor`
- `Task`
- `TaskStatus`
- `TelemetrySample`
- `UserPreferences`
- `WingetConnector`
- `Workflow`
- `__init__`
- `_add_log_blocking`
- `_find_component`
- `_sync_kb_blocking`
- `_sync_state_blocking`
- `accept_license`
- `accept_telemetry_consent`
- `add_document`
- `add_history`
- `add_log`
- `apply_update`
- `approve_and_clear`
- `author`
- `build_context`
- `call`
- `cancel_schedule`
- `check`
- `check_for_updates`
- `check_health`
- `check_models`
- `collect`
- `create_backup`
- `create_mission`
- `create_plan`
- `decline_telemetry_consent`
- `delete`
- `delete_secret`
- `descriptor`
- `disable_plugin`
- `discover`
- `download`
- `enable_plugin`
- `ensure_directory`
- `execute_mission`
- `execute_pipeline`
- `execute_plan`
- `execute_task`
- `get_apps_path`
- `get_best_runtime`
- `get_cache_dir`
- `get_config`
- `get_descriptor`
- `get_disk_info`
- `get_document_count`
- `get_downloads_dir`
- `get_event_history`
- `get_events`
- `get_fastest_drive`
- `get_free_space_gb`
- `get_hardware_all`
- `get_history`
- `get_index`
- `get_last_results`
- `get_license`
- `get_logs`
- `get_machine_id`
- `get_missions`
- `get_model_path`
- `get_models_path`
- `get_or_create_api_key`
- `get_outputs_dir`
- `get_package`
- `get_path`
- `get_pending`
- `get_platform_health`
- `get_profile`
- `get_rag_path`
- `get_secret`
- `get_stats`
- `get_status`
- `get_telemetry`
- `get_telemetry_consent`
- `get_temp_dir`
- `handle_command`
- `hardware_hash`
- `health_check`
- `id`
- `install_mission`
- `install_plugin`
- `is_available`
- `list_available`
- `list_available_missions`
- `list_backups`
- `list_connectors`
- `list_installed`
- `list_plugins`
- `list_runtimes`
- `list_schedules`
- `load_all_machine`
- `load_all_procedures`
- `load_plugins`
- `log_event`
- `machine_identity`
- `matches`
- `name`
- `open_browser`
- `recommend_models`
- `record_execution`
- `record_experience`
- `register_command`
- `reingest_rag_sources`
- `reject`
- `repair`
- `req`
- `req_exec`
- `request_approval`
- `resolve_mission`
- `restore_backup`
- `run_disk_benchmark`
- `run_runtime_benchmark`
- `schedule_mission`
- `send`
- `send_notification`
- `set_persistence_callback`
- `setup_file_logging`
- `shutdown_event`
- `source_id`
- `start_server`
- `startup_event`
- `stop_server`
- `store_secret`
- `subscribe`
- `test_each_mission_has_unique_id`
- `test_kernel_approve_without_active_mission_raises_error`
- `test_kernel_approves_active_mission`
- `test_kernel_registers_mission_and_sets_waiting_approval`
- `test_kernel_rejects_active_mission`
- `test_metadata_is_serialized`
- `test_parameters_default_to_empty_dict`
- `test_planner_creates_mission_with_correct_steps`
- `test_registered_mission_is_same_instance`
- `test_status_is_serialized_as_string`
- `test_step_action_is_enum_instance`
- `test_step_parameters_are_serialized`
- `test_to_dict_serialization`
- `trigger_telemetry_sync`
- `uninstall`
- `unregister_engine`
- `update_machine`
- `version`

---


## 5. Instanciações (Quem cria quem)

### `api_server.py`
  - Instancia: `FastAPI`
  - Instancia: `PhoenixKernel`
  - Instancia: `Path`
  - Instancia: `FileResponse`
  - Instancia: `HTTPException`
  - Instancia: `HTTPException`
  - Instancia: `HTTPException`
  - Instancia: `HTTPException`

### `generate_phoenix_map.py`
  - Instancia: `Path`

### `install_phoenix_kernel.py`
  - Instancia: `Path`

### `phoenix_models_migration.py`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_runtime_migration.py`
  - Instancia: `Path`

### `setup_environment.py`
  - Instancia: `Path`
  - Instancia: `Path`

### `setup_platform.py`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_kernel/cloud_sync.py`
  - Instancia: `FileNotFoundError`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_kernel/kernel.py`
  - Instancia: `EventBus`
  - Instancia: `PlatformKernel`
  - Instancia: `StateEngine`
  - Instancia: `Profile`
  - Instancia: `MachineContext`
  - Instancia: `BootPlan`
  - Instancia: `FirestoreSync`
  - Instancia: `ModelManager`

### `phoenix_kernel/paths.py`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`

### `tests/test_mission_kernel.py`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionKernel`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionKernel`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionKernel`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionKernel`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionKernel`
  - Instancia: `Mission`
  - Instancia: `MissionPlanner`
  - Instancia: `MissionPlanner`
  - Instancia: `Mission`
  - Instancia: `MissionStep`

### `tools/setup_firestore.py`
  - Instancia: `Path`

### `core/events/bus.py`
  - Instancia: `ValueError`

### `core/kernel/kernel.py`
  - Instancia: `ServiceRegistry`
  - Instancia: `EventBus`
  - Instancia: `LifecycleManager`

### `core/kernel/plugin_loader.py`
  - Instancia: `Path`

### `phoenix_kernel/core/planner.py`
  - Instancia: `Mission`
  - Instancia: `MissionStep`

### `phoenix_kernel/discovery/discovery_core.py`
  - Instancia: `CPUInfo`
  - Instancia: `HardwareSnapshot`
  - Instancia: `StorageDeviceInfo`
  - Instancia: `GPUInfo`
  - Instancia: `MemoryInfo`
  - Instancia: `MachineIdentity`

### `phoenix_kernel/discovery/discovery_engine.py`
  - Instancia: `HardwareDiscoveryCore`

### `phoenix_kernel/intelligence/knowledge_engine.py`
  - Instancia: `MemoryLoader`
  - Instancia: `Path`
  - Instancia: `RuntimeError`

### `phoenix_kernel/intelligence/memory_loader.py`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `MemoryCard`
  - Instancia: `MemoryCard`
  - Instancia: `MemoryCard`

### `phoenix_kernel/intelligence/reasoning_engine.py`
  - Instancia: `KnowledgeEngine`
  - Instancia: `ExecutionPlan`
  - Instancia: `Mission`
  - Instancia: `MissionAction`
  - Instancia: `MissionStep`

### `phoenix_kernel/models/inventory.py`
  - Instancia: `Path`

### `phoenix_kernel/models/model_manager.py`
  - Instancia: `Path`

### `phoenix_kernel/models/model_scanner.py`
  - Instancia: `Path`

### `phoenix_kernel/planner/engine.py`
  - Instancia: `KnowledgeEngine`
  - Instancia: `RuleEvaluator`

### `phoenix_kernel/planner/evaluator.py`
  - Instancia: `ExecutionPlan`
  - Instancia: `ExecutionPlan`
  - Instancia: `ExecutionPlan`

### `phoenix_kernel/planner/knowledge_engine.py`
  - Instancia: `MemoryLoader`
  - Instancia: `Path`
  - Instancia: `RuntimeError`

### `phoenix_kernel/resident/memory.py`
  - Instancia: `Path`

### `phoenix_kernel/resident/resident_manager.py`
  - Instancia: `ReasoningEngine`
  - Instancia: `ModelManager`
  - Instancia: `ExecutionPlan`

### `phoenix_kernel/runtime/engine.py`
  - Instancia: `EngineDescriptor`
  - Instancia: `LlamaCppDriver`
  - Instancia: `Path`
  - Instancia: `SdCppDriver`
  - Instancia: `WhisperDriver`
  - Instancia: `PiperDriver`
  - Instancia: `ComfyUIDriver`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`
  - Instancia: `RuntimeDescriptor`
  - Instancia: `ExecutionResult`
  - Instancia: `Capability`
  - Instancia: `Event`
  - Instancia: `Event`

### `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Instancia: `EngineDescriptor`
  - Instancia: `OllamaDriver`
  - Instancia: `LlamaCppDriver`
  - Instancia: `ExecutionResult`
  - Instancia: `Path`
  - Instancia: `SdCppDriver`
  - Instancia: `WhisperDriver`
  - Instancia: `PiperDriver`
  - Instancia: `ComfyUIDriver`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`
  - Instancia: `RuntimeDescriptor`
  - Instancia: `ExecutionPlan`
  - Instancia: `Capability`
  - Instancia: `Event`
  - Instancia: `Event`

### `phoenix_kernel/services/catalog.py`
  - Instancia: `Path`

### `phoenix_kernel/services/engine.py`
  - Instancia: `ProvisioningManager`
  - Instancia: `PackageManager`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_kernel/services/package_manager.py`
  - Instancia: `Path`
  - Instancia: `CatalogEngine`
  - Instancia: `ProvisioningManager`

### `phoenix_kernel/services/platform_process.py`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_kernel/services/provisioning.py`
  - Instancia: `CatalogEngine`
  - Instancia: `Path`

### `phoenix_kernel/shared/hardware_provider.py`
  - Instancia: `Computer`

### `phoenix_kernel/shared/storage.py`
  - Instancia: `StorageManager`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_kernel/telemetry/core.py`
  - Instancia: `Computer`

### `phoenix_kernel/discovery/providers/factory.py`
  - Instancia: `NotImplementedError`
  - Instancia: `WindowsDiscoveryProvider`
  - Instancia: `LinuxDiscoveryProvider`

### `phoenix_kernel/discovery/providers/linux.py`
  - Instancia: `CPUInfo`
  - Instancia: `MotherboardInfo`
  - Instancia: `MemoryInfo`
  - Instancia: `HardwareSnapshot`
  - Instancia: `MemoryInfo`
  - Instancia: `GPUInfo`
  - Instancia: `StorageInfo`
  - Instancia: `MemoryInfo`

### `phoenix_kernel/discovery/providers/windows.py`
  - Instancia: `CPUInfo`
  - Instancia: `MotherboardInfo`
  - Instancia: `MemoryInfo`
  - Instancia: `HardwareSnapshot`
  - Instancia: `MemoryInfo`
  - Instancia: `MotherboardInfo`
  - Instancia: `GPUInfo`
  - Instancia: `StorageInfo`

### `phoenix_kernel/rag/source_docs/audio_translation_script.py`
  - Instancia: `GoogleTranslator`

### `phoenix_kernel/runtime/builders/flux_builder.py`
  - Instancia: `MissingComponent`

### `phoenix_kernel/runtime/builders/registry.py`
  - Instancia: `BuilderNotSupported`

### `phoenix_kernel/runtime/drivers/comfyui.py`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`

### `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Instancia: `RuntimeStatus`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`
  - Instancia: `ExecutionResult`
  - Instancia: `ExecutionResult`
  - Instancia: `Path`
  - Instancia: `Path`

### `phoenix_kernel/runtime/drivers/ollama.py`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`
  - Instancia: `Path`

### `phoenix_kernel/runtime/drivers/piper.py`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`

### `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Instancia: `ExecutableNotFound`
  - Instancia: `RuntimeCapabilities`
  - Instancia: `RuntimeStatus`
  - Instancia: `GenerationFailed`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`
  - Instancia: `ExecutionResult`
  - Instancia: `ExecutionResult`
  - Instancia: `Path`

### `phoenix_kernel/runtime/drivers/whisper.py`
  - Instancia: `RuntimeStatus`
  - Instancia: `ExecutionResult`

### `phoenix_kernel/runtime/executors/subprocess_executor.py`
  - Instancia: `GenerationFailed`
  - Instancia: `GenerationFailed`

### `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Instancia: `GenerationProfile`
  - Instancia: `ModelDescriptor`
  - Instancia: `ModelNotFound`
  - Instancia: `ModelNotFound`
  - Instancia: `CatalogInconsistency`
  - Instancia: `CatalogInconsistency`
  - Instancia: `ModelArchitecture`
  - Instancia: `MissingComponent`
  - Instancia: `CatalogInconsistency`

### `phoenix_kernel/telemetry/providers/factory.py`
  - Instancia: `NotImplementedError`
  - Instancia: `WindowsTelemetryProvider`
  - Instancia: `LinuxTelemetryProvider`

### `phoenix_kernel/telemetry/providers/linux.py`
  - Instancia: `TelemetrySnapshot`

### `phoenix_kernel/telemetry/providers/windows.py`
  - Instancia: `TelemetrySnapshot`


---


## 6. Chamadas de Sistema (HTTP e Subprocess)

### `phoenix_kernel/cloud_sync.py`
  - **HTTP:**
    - `socket.gethostname`

### `tools/setup_firestore.py`
  - **HTTP:**
    - `socket.gethostname`
    - `socket.gethostname`

### `phoenix_kernel/intelligence/web_search.py`
  - **HTTP:**
    - `httpx.AsyncClient`

### `phoenix_kernel/models/model_manager.py`
  - **HTTP:**
    - `httpx.AsyncClient`
    - `httpx.AsyncClient`

### `phoenix_kernel/services/lmstudio_service.py`
  - **HTTP:**
    - `httpx.AsyncClient`

### `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - **HTTP:**
    - `httpx.AsyncClient`
    - `httpx.AsyncClient`


---


## 7. Alvos Específicos Detectados (llama.cpp, ollama, vulkan, etc)

### `apiengine`
  - Encontrado em: `phoenix_kernel/kernel.py`
  - Encontrado em: `phoenix_kernel/api/engine.py`

### `comfyui`
  - Encontrado em: `phoenix_kernel/runtime/engine.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/comfyui.py`

### `executionplan`
  - Encontrado em: `core/domain/execution.py`
  - Encontrado em: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Encontrado em: `phoenix_kernel/planner/evaluator.py`
  - Encontrado em: `phoenix_kernel/resident/resident_manager.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `executionresult`
  - Encontrado em: `core/domain/execution.py`
  - Encontrado em: `phoenix_kernel/runtime/engine.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/comfyui.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/ollama.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/piper.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/whisper.py`

### `kernel`
  - Encontrado em: `api_server.py`
  - Encontrado em: `phoenix_models_migration.py`
  - Encontrado em: `phoenix_kernel/cloud_sync.py`
  - Encontrado em: `phoenix_kernel/kernel.py`
  - Encontrado em: `tests/test_mission_kernel.py`
  - Encontrado em: `core/kernel/kernel.py`
  - Encontrado em: `core/kernel/plugin_base.py`
  - Encontrado em: `core/kernel/plugin_context.py`
  - Encontrado em: `core/kernel/plugin_loader.py`
  - Encontrado em: `core/kernel/__init__.py`
  - Encontrado em: `phoenix_kernel/api/engine.py`
  - Encontrado em: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Encontrado em: `phoenix_kernel/models/inventory.py`
  - Encontrado em: `phoenix_kernel/models/model_manager.py`
  - Encontrado em: `phoenix_kernel/models/model_scanner.py`
  - Encontrado em: `phoenix_kernel/planner/knowledge_engine.py`
  - Encontrado em: `phoenix_kernel/resident/resident_manager.py`
  - Encontrado em: `phoenix_kernel/runtime/engine.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Encontrado em: `phoenix_kernel/discovery/providers/base.py`
  - Encontrado em: `phoenix_kernel/discovery/providers/linux.py`
  - Encontrado em: `phoenix_kernel/discovery/providers/windows.py`
  - Encontrado em: `phoenix_kernel/runtime/builders/base_builder.py`
  - Encontrado em: `phoenix_kernel/runtime/builders/flux_builder.py`
  - Encontrado em: `phoenix_kernel/runtime/builders/registry.py`
  - Encontrado em: `phoenix_kernel/runtime/builders/sd15_builder.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Encontrado em: `phoenix_kernel/runtime/executors/subprocess_executor.py`
  - Encontrado em: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Encontrado em: `phoenix_kernel/telemetry/providers/base.py`
  - Encontrado em: `phoenix_kernel/telemetry/providers/linux.py`
  - Encontrado em: `phoenix_kernel/telemetry/providers/windows.py`

### `mission`
  - Encontrado em: `tests/test_mission_kernel.py`
  - Encontrado em: `core/contracts/mission.py`
  - Encontrado em: `core/contracts/__init__.py`
  - Encontrado em: `core/domain/workflows.py`
  - Encontrado em: `phoenix_kernel/core/enums.py`
  - Encontrado em: `phoenix_kernel/core/exceptions.py`
  - Encontrado em: `phoenix_kernel/core/models.py`
  - Encontrado em: `phoenix_kernel/core/planner.py`
  - Encontrado em: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Encontrado em: `phoenix_kernel/resident/resident_manager.py`

### `ollama`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/ollama.py`

### `piper`
  - Encontrado em: `phoenix_kernel/runtime/engine.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/piper.py`

### `plannerengine`
  - Encontrado em: `phoenix_kernel/kernel.py`
  - Encontrado em: `phoenix_kernel/planner/engine.py`

### `residentmanager`
  - Encontrado em: `phoenix_kernel/kernel.py`
  - Encontrado em: `phoenix_kernel/intelligence/interfaces.py`
  - Encontrado em: `phoenix_kernel/resident/interfaces.py`
  - Encontrado em: `phoenix_kernel/resident/resident_manager.py`

### `runtimeengine`
  - Encontrado em: `phoenix_kernel/kernel.py`
  - Encontrado em: `phoenix_kernel/runtime/engine.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `whisper`
  - Encontrado em: `phoenix_kernel/runtime/engine.py`
  - Encontrado em: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Encontrado em: `phoenix_kernel/runtime/drivers/whisper.py`


---


## 8. Índice Reverso de Chamadas

Para cada símbolo (classe ou função) definido no projeto, lista quem o chama.

### `ApiEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `BudgetEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `BuilderNotSupported`
  - Chamado por: `phoenix_kernel/runtime/builders/registry.py`

### `CPUInfo`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `Capability`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `CatalogEngine`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`

### `CatalogInconsistency`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `ComfyUIDriver`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `DiscoveryEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `EngineDescriptor`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `Event`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `EventBus`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `core/kernel/kernel.py`

### `ExecutableNotFound`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `ExecutionPlan`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `ExecutionResult`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/comfyui.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/piper.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/whisper.py`

### `FirestoreSync`
  - Chamado por: `phoenix_kernel/kernel.py`

### `GPUInfo`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `GenerationFailed`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/executors/subprocess_executor.py`
  - Chamado por: `phoenix_kernel/runtime/executors/subprocess_executor.py`

### `GenerationProfile`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `HardwareDiscoveryCore`
  - Chamado por: `phoenix_kernel/discovery/discovery_engine.py`

### `HardwareSnapshot`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `KnowledgeEngine`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/planner/engine.py`

### `LifecycleManager`
  - Chamado por: `core/kernel/kernel.py`

### `LinuxDiscoveryProvider`
  - Chamado por: `phoenix_kernel/discovery/providers/factory.py`

### `LinuxTelemetryProvider`
  - Chamado por: `phoenix_kernel/telemetry/providers/factory.py`

### `LlamaCppDriver`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `MachineContext`
  - Chamado por: `phoenix_kernel/kernel.py`

### `MachineIdentity`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `MemoryCard`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`

### `MemoryInfo`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `MemoryLoader`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `MissingComponent`
  - Chamado por: `phoenix_kernel/runtime/builders/flux_builder.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `Mission`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `phoenix_kernel/core/planner.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`

### `MissionAction`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`

### `MissionPlanner`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`

### `MissionStep`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `phoenix_kernel/core/planner.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`

### `ModelArchitecture`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `ModelDescriptor`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `ModelManager`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `ModelNotFound`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `ModelsEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `MotherboardInfo`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `OllamaDriver`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `PackageManager`
  - Chamado por: `phoenix_kernel/services/engine.py`

### `PhoenixKernel`
  - Chamado por: `api_server.py`

### `PiperDriver`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `PlannerEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `PlatformKernel`
  - Chamado por: `phoenix_kernel/kernel.py`

### `Profile`
  - Chamado por: `phoenix_kernel/kernel.py`

### `ProvisioningManager`
  - Chamado por: `phoenix_kernel/services/engine.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`

### `ReasoningEngine`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `ResidentManager`
  - Chamado por: `phoenix_kernel/kernel.py`

### `RuleEvaluator`
  - Chamado por: `phoenix_kernel/planner/engine.py`

### `RuntimeCapabilities`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `RuntimeDescriptor`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `RuntimeEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `RuntimeStatus`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/comfyui.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/piper.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/whisper.py`

### `SdCppDriver`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `SecurityEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `ServiceRegistry`
  - Chamado por: `core/kernel/kernel.py`

### `ServicesEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `StateEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `StorageDeviceInfo`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `StorageInfo`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `StorageManager`
  - Chamado por: `phoenix_kernel/shared/storage.py`

### `TelemetryEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `TelemetrySnapshot`
  - Chamado por: `phoenix_kernel/telemetry/providers/linux.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/windows.py`

### `ValidationEngine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `WhisperDriver`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `WindowsDiscoveryProvider`
  - Chamado por: `phoenix_kernel/discovery/providers/factory.py`

### `WindowsTelemetryProvider`
  - Chamado por: `phoenix_kernel/telemetry/providers/factory.py`

### `_amd_gpu_cards`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_call_driver_start`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `_check_device_alerts`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `_check_health`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`

### `_classify_vendor`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `_clean_pci_name`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`

### `_cloud_sync_loop`
  - Chamado por: `phoenix_kernel/kernel.py`

### `_collect_sensors`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_compute_identity`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `_disk_temps_by_device`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_download_components`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`

### `_ensure_default_model`
  - Chamado por: `phoenix_kernel/kernel.py`

### `_execute_mission_background`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `_find_engine_binary`
  - Chamado por: `phoenix_kernel/services/engine.py`
  - Chamado por: `phoenix_kernel/services/engine.py`

### `_find_executable`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `_find_model_file`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`

### `_find_package`
  - Chamado por: `phoenix_kernel/services/package_manager.py`

### `_get_all_hardware_sensors_linux`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_get_client`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`

### `_get_computer`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_get_cpu_info`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `_get_disk_priorities`
  - Chamado por: `phoenix_kernel/services/install_target.py`

### `_get_gpu_info`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `_get_gpu_raw`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `_get_gpu_sensors_linux`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_get_gpu_static_specs_linux`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_get_hardware_context`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`

### `_get_linux_gpu`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`

### `_get_linux_hardware`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`

### `_get_memory_info`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `_get_motherboard_info`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`

### `_get_physical_disks_raw`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `_get_storage_and_motherboard`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `_get_storage_info`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`

### `_get_storage_raw`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `_get_vram_via_dxdiag`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `_get_win_computer`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`

### `_get_windows_gpu`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`

### `_get_windows_hardware`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`

### `_gpu_name_linux`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_hash`
  - Chamado por: `phoenix_kernel/models/model_scanner.py`

### `_install_docker`
  - Chamado por: `phoenix_kernel/services/provisioning.py`

### `_install_git`
  - Chamado por: `phoenix_kernel/services/provisioning.py`

### `_install_pip`
  - Chamado por: `phoenix_kernel/services/provisioning.py`

### `_install_winget`
  - Chamado por: `phoenix_kernel/services/provisioning.py`

### `_is_docker_running`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`

### `_lmsensors_devices`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_load`
  - Chamado por: `phoenix_kernel/resident/memory.py`

### `_load_config`
  - Chamado por: `phoenix_kernel/shared/storage.py`

### `_load_connectors`
  - Chamado por: `phoenix_kernel/services/catalog.py`

### `_load_manifest`
  - Chamado por: `phoenix_kernel/paths.py`

### `_load_packages`
  - Chamado por: `phoenix_kernel/services/catalog.py`

### `_log`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`

### `_log_diagnostic_once`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_parse_json`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`

### `_parse_lsblk_size_gb`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_parse_markdown`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`

### `_parse_plain`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`

### `_parse_simple_yaml`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`

### `_read_sysfs_int`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_record`
  - Chamado por: `phoenix_kernel/models/model_scanner.py`

### `_render_section`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `_run`
  - Chamado por: `setup_platform.py`
  - Chamado por: `setup_platform.py`
  - Chamado por: `setup_platform.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`

### `_run_cmd`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`

### `_save_vram_cache`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`

### `_step`
  - Chamado por: `phoenix_kernel/core/planner.py`
  - Chamado por: `phoenix_kernel/core/planner.py`
  - Chamado por: `phoenix_kernel/core/planner.py`

### `_storage_devices_linux`
  - Chamado por: `phoenix_kernel/telemetry/core.py`

### `_stream_log`
  - Chamado por: `phoenix_kernel/services/platform_process.py`

### `_supervise`
  - Chamado por: `phoenix_kernel/services/platform_process.py`

### `_thermal_guard`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `_watchdog_loop`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `analyze_machine`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `approve_and_execute`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `backup_file`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`

### `boot`
  - Chamado por: `api_server.py`

### `bootstrap`
  - Chamado por: `tools/setup_firestore.py`

### `build`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `build_platform`
  - Chamado por: `setup_platform.py`
  - Chamado por: `phoenix_kernel/kernel.py`

### `check_integrity`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `clear`
  - Chamado por: `core/kernel/lifecycle.py`
  - Chamado por: `core/kernel/lifecycle.py`

### `connect`
  - Chamado por: `tools/setup_firestore.py`

### `create`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`

### `create_dir`
  - Chamado por: `setup_environment.py`

### `create_example`
  - Chamado por: `tools/setup_firestore.py`

### `create_file`
  - Chamado por: `setup_environment.py`
  - Chamado por: `setup_environment.py`
  - Chamado por: `setup_environment.py`
  - Chamado por: `setup_environment.py`

### `create_folder_structure`
  - Chamado por: `phoenix_models_migration.py`

### `create_markdown`
  - Chamado por: `generate_phoenix_map.py`

### `create_runtime_architecture`
  - Chamado por: `phoenix_runtime_migration.py`

### `describe_image`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `discover_hardware`
  - Chamado por: `phoenix_kernel/kernel.py`

### `discover_workspace`
  - Chamado por: `phoenix_models_migration.py`

### `download_model`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `embed`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `ensure_dir`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`

### `evaluate`
  - Chamado por: `phoenix_kernel/planner/engine.py`

### `evaluate_machine`
  - Chamado por: `phoenix_kernel/state.py`

### `execute`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `extract_python_info`
  - Chamado por: `generate_phoenix_map.py`

### `find`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`

### `fix_imports`
  - Chamado por: `phoenix_runtime_migration.py`

### `generate_report`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`

### `get`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `core/events/bus.py`
  - Chamado por: `core/events/bus.py`
  - Chamado por: `core/events/bus.py`
  - Chamado por: `core/kernel/kernel.py`
  - Chamado por: `core/kernel/registry.py`
  - Chamado por: `core/kernel/registry.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/budget/engine.py`
  - Chamado por: `phoenix_kernel/budget/engine.py`
  - Chamado por: `phoenix_kernel/budget/engine.py`
  - Chamado por: `phoenix_kernel/core/event_bus.py`
  - Chamado por: `phoenix_kernel/core/planner.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/web_search.py`
  - Chamado por: `phoenix_kernel/intelligence/web_search.py`
  - Chamado por: `phoenix_kernel/intelligence/web_search.py`
  - Chamado por: `phoenix_kernel/intelligence/web_search.py`
  - Chamado por: `phoenix_kernel/models/engine.py`
  - Chamado por: `phoenix_kernel/models/inventory.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_scanner.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/resident/decision_engine.py`
  - Chamado por: `phoenix_kernel/resident/research_connector.py`
  - Chamado por: `phoenix_kernel/resident/research_connector.py`
  - Chamado por: `phoenix_kernel/resident/research_connector.py`
  - Chamado por: `phoenix_kernel/resident/research_connector.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/lmstudio_service.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/runtime/builders/registry.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/ollama.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/linux.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/linux.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/linux.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/windows.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/windows.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/windows.py`

### `get_all_hardware_sensors`
  - Chamado por: `api_server.py`

### `get_best_workspace_path`
  - Chamado por: `phoenix_kernel/services/install_target.py`

### `get_category_path`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `get_connector`
  - Chamado por: `phoenix_kernel/services/provisioning.py`

### `get_db_path`
  - Chamado por: `phoenix_kernel/models/inventory.py`
  - Chamado por: `phoenix_kernel/models/inventory.py`

### `get_discovery_provider`
  - Chamado por: `phoenix_kernel/discovery/engine.py`

### `get_environment_status`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `get_execution_recipe`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `get_gpu_sensors`
  - Chamado por: `phoenix_kernel/telemetry/providers/linux.py`
  - Chamado por: `phoenix_kernel/telemetry/providers/windows.py`

### `get_gpu_static_specs`
  - Chamado por: `phoenix_kernel/discovery/providers/windows.py`

### `get_inventory_db`
  - Chamado por: `phoenix_kernel/models/inventory.py`

### `get_live_metrics`
  - Chamado por: `phoenix_kernel/state.py`

### `get_machine_context`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `get_metrics`
  - Chamado por: `phoenix_kernel/telemetry/engine.py`

### `get_model_and_rag_status`
  - Chamado por: `phoenix_kernel/state.py`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `get_models_base`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/models/model_scanner.py`
  - Chamado por: `phoenix_kernel/models/model_scanner.py`

### `get_or_create_machine_id`
  - Chamado por: `phoenix_kernel/cloud_sync.py`

### `get_state`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `get_telemetry_provider`
  - Chamado por: `phoenix_kernel/telemetry/engine.py`

### `get_workspace`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`

### `get_workspace_path`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `grant_consent`
  - Chamado por: `api_server.py`

### `has_consent`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/kernel.py`

### `health`
  - Chamado por: `core/kernel/lifecycle.py`

### `health_check_all`
  - Chamado por: `core/kernel/kernel.py`

### `initialize`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `core/kernel/lifecycle.py`
  - Chamado por: `phoenix_kernel/planner/engine.py`

### `initialize_all`
  - Chamado por: `core/kernel/kernel.py`

### `install`
  - Chamado por: `install_phoenix_kernel.py`

### `install_node_via_winget`
  - Chamado por: `setup_platform.py`

### `install_package`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/services/engine.py`

### `install_service`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `is_cli_installed`
  - Chamado por: `phoenix_kernel/services/lmstudio_service.py`

### `is_node_installed`
  - Chamado por: `setup_platform.py`

### `is_platform_built`
  - Chamado por: `setup_platform.py`

### `is_running`
  - Chamado por: `phoenix_kernel/services/lmstudio_service.py`
  - Chamado por: `phoenix_kernel/services/lmstudio_service.py`

### `list_engines`
  - Chamado por: `core/kernel/kernel.py`
  - Chamado por: `core/kernel/lifecycle.py`

### `list_packages`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `load`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_kernel/cloud_sync.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/models/inventory.py`
  - Chamado por: `phoenix_kernel/models/inventory.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/catalog.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/services/package_manager.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/pipeline/catalog_pipeline.py`

### `load_intrinsic`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `load_intrinsic_memory`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `load_machine_file`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `load_machine_id`
  - Chamado por: `tools/setup_firestore.py`

### `load_manifest`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `load_procedure`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/intelligence/memory_loader.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `load_rag_source_docs`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `log`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`

### `main`
  - Chamado por: `install_phoenix_kernel.py`
  - Chamado por: `phoenix_models_migration.py`

### `migrate_existing_models`
  - Chamado por: `phoenix_models_migration.py`

### `patch_drivers`
  - Chamado por: `phoenix_models_migration.py`

### `plan_inference`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `plan_mission`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `process_command`
  - Chamado por: `api_server.py`

### `process_intent`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `publish`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `pull_model`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `query`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `query_knowledge`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `refresh`
  - Chamado por: `phoenix_models_migration.py`

### `register`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `core/kernel/plugin_loader.py`
  - Chamado por: `phoenix_kernel/runtime/builders/registry.py`
  - Chamado por: `phoenix_kernel/runtime/builders/registry.py`

### `register_engine`
  - Chamado por: `core/kernel/kernel.py`

### `rename_numbered_dirs`
  - Chamado por: `phoenix_runtime_migration.py`

### `resolve`
  - Chamado por: `install_phoenix_kernel.py`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `phoenix_kernel/paths.py`
  - Chamado por: `tools/setup_firestore.py`
  - Chamado por: `core/kernel/kernel.py`
  - Chamado por: `core/kernel/lifecycle.py`
  - Chamado por: `core/kernel/lifecycle.py`
  - Chamado por: `core/kernel/lifecycle.py`
  - Chamado por: `core/kernel/plugin_context.py`
  - Chamado por: `core/kernel/plugin_loader.py`
  - Chamado por: `core/kernel/plugin_loader.py`
  - Chamado por: `phoenix_kernel/models/model_manager.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/shared/storage.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `resolve_package`
  - Chamado por: `api_server.py`

### `resolve_paths`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `revoke_consent`
  - Chamado por: `api_server.py`

### `run`
  - Chamado por: `api_server.py`
  - Chamado por: `setup_platform.py`
  - Chamado por: `setup_platform.py`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/install_target.py`
  - Chamado por: `phoenix_kernel/services/lmstudio_service.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/services/provisioning.py`
  - Chamado por: `phoenix_kernel/shared/hardware_provider.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/telemetry/core.py`
  - Chamado por: `phoenix_kernel/discovery/providers/linux.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/install/connectors/connectors.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `save`
  - Chamado por: `phoenix_kernel/resident/memory.py`
  - Chamado por: `phoenix_kernel/resident/memory.py`

### `scan_all`
  - Chamado por: `phoenix_models_migration.py`
  - Chamado por: `phoenix_kernel/models/inventory.py`

### `scan_files`
  - Chamado por: `generate_phoenix_map.py`

### `search`
  - Chamado por: `phoenix_kernel/discovery/discovery_core.py`
  - Chamado por: `phoenix_kernel/planner/evaluator.py`

### `search_rag`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `search_web`
  - Chamado por: `phoenix_kernel/api/engine.py`
  - Chamado por: `phoenix_kernel/intelligence/reasoning_engine.py`

### `set_context`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/kernel.py`

### `set_knowledge_engine`
  - Chamado por: `phoenix_kernel/kernel.py`

### `shutdown`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `core/kernel/lifecycle.py`

### `shutdown_all`
  - Chamado por: `core/kernel/kernel.py`

### `start`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`

### `start_supervised`
  - Chamado por: `phoenix_kernel/kernel.py`

### `status`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`

### `stop`
  - Chamado por: `phoenix_kernel/kernel.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/engine.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/runtime_engine OLD.py`
  - Chamado por: `phoenix_kernel/runtime/drivers/llama_cpp.py`

### `sync_knowledge_base`
  - Chamado por: `api_server.py`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/kernel.py`

### `sync_machine_state`
  - Chamado por: `api_server.py`
  - Chamado por: `phoenix_kernel/kernel.py`

### `to_dict`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `tests/test_mission_kernel.py`
  - Chamado por: `phoenix_kernel/resident/resident_manager.py`

### `traduzir_srt`
  - Chamado por: `phoenix_kernel/rag/source_docs/audio_translation_script.py`

### `try_start_server`
  - Chamado por: `phoenix_kernel/kernel.py`

### `update_catalog`
  - Chamado por: `phoenix_models_migration.py`

### `upsert`
  - Chamado por: `phoenix_kernel/intelligence/knowledge_engine.py`
  - Chamado por: `phoenix_kernel/planner/knowledge_engine.py`

### `validate`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `validate_disk`
  - Chamado por: `phoenix_kernel/runtime/drivers/sd_cpp.py`

### `validate_system`
  - Chamado por: `phoenix_kernel/api/engine.py`

### `write_file`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
  - Chamado por: `phoenix_runtime_migration.py`
