# Phoenix 4.5 — Image Generation & Provisioning Bridge Contract

## Purpose

PHX-PHASE6I separates two application domains that were still reachable only
through ResidentManager internals:

- image-generation workflow and installed-image-model discovery;
- provisioning / package installation / asset download workflow.

ResidentManager remains a valid workflow coordinator and compatibility facade.
ExecutionOrchestrator remains the computational authority. Phoenix Diffusion
keeps all native image backend / auto-fit / model-load intelligence.

## Ownership

- `ImageGenerationService`
  - discovers installed image checkpoints;
  - filters VAE/CLIP/text-encoder component files;
  - resolves requested model vs disk truth;
  - performs direct chat image generation;
  - performs mission image generation after provisioning when needed;
  - calls `ExecutionGateway`, never `RuntimeEngine` directly.

- `ProvisioningService`
  - exposes environment status;
  - delegates connector/service/package installation to existing `ServicesEngine`;
  - delegates model-asset download/cache to existing `AssetManager`;
  - does not reimplement Docker/Git/Winget/Pip or HTTP download mechanics.

- `MissionService`
  - no longer uses `__getattr__` to treat ResidentManager as a namespace;
  - `VALIDATE_ENVIRONMENT` / `INSTALL_PACKAGE` -> `ProvisioningService`;
  - `DOWNLOAD_MODEL` -> `ProvisioningService` + `ImageGenerationService` disk truth;
  - `LOAD_MODEL` / `UNLOAD_MODEL` -> `ModelRuntimeService`;
  - `SWITCH_RUNTIME` -> `ExecutionGateway`;
  - `GENERATE_IMAGE` -> `ImageGenerationService`.

## Compatibility

Legacy methods remain on ResidentManager:

- `_discover_installed_image_models()`
- `_resolve_image_model_target()`
- `list_installed_image_models()`
- `generate_image_direct()`

They are facades delegating to `ImageGenerationService`.

## Non-goals

This phase does not move or rewrite:

- Phoenix Diffusion worker/native bridge;
- stable-diffusion.cpp profiles;
- AUTO placement / leases / correctness;
- AssetManager providers;
- PackageManager / ProvisioningManager mechanics.

The goal is one owner per application responsibility, not fewer modules.
