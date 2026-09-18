# Phoenix Runtime Migration Report

**Timestamp:** 2026-07-28T14:40:21.074093

## Created (14)
- File generated: phoenix_kernel\runtime\builders\__init__.py
- File generated: phoenix_kernel\runtime\executors\__init__.py
- File generated: phoenix_kernel\runtime\validators\__init__.py
- File generated: phoenix_kernel\runtime\contracts\__init__.py
- File generated: phoenix_kernel\runtime\registry\__init__.py
- File generated: phoenix_kernel\runtime\pipeline\__init__.py
- File generated: phoenix_kernel\runtime\contracts\model_contracts.py
- File generated: phoenix_kernel\runtime\pipeline\catalog_pipeline.py
- File generated: phoenix_kernel\runtime\builders\base_builder.py
- File generated: phoenix_kernel\runtime\builders\flux_builder.py
- File generated: phoenix_kernel\runtime\builders\sd15_builder.py
- File generated: phoenix_kernel\runtime\builders\registry.py
- File generated: phoenix_kernel\runtime\executors\subprocess_executor.py
- File generated: phoenix_kernel\runtime\drivers\sd_cpp.py

## Backups (7)
- Backup created: api_server.py.bak
- Backup created: phoenix_runtime_migration.py.bak
- Backup created: kernel.py.bak
- Backup created: windows.py.bak
- Backup created: resident_manager.py.bak
- Backup created: llama_cpp.py.bak
- Backup created: sd_cpp.py.bak

## Imports Fixed (6)
- Updated imports in: api_server.py
- Updated imports in: phoenix_runtime_migration.py
- Updated imports in: phoenix_kernel\kernel.py
- Updated imports in: phoenix_kernel\discovery\providers\windows.py
- Updated imports in: phoenix_kernel\resident\resident_manager.py
- Updated imports in: phoenix_kernel\runtime\drivers\llama_cpp.py

## Next Steps
1. Review the backup files (.bak) to ensure no custom logic was lost.
2. Update `kernel.py` to inject `RuntimeCapabilities` into `SdCppDriver`.
3. Ensure `catalog/models.json` contains the `components` and `default_generation` blocks for FLUX.
