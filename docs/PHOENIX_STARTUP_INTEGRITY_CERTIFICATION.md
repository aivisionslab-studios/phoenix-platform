# PHOENIX PHASE7O — Startup Integrity / Installed Build Certification

## Objetivo

PHASE7O certifica a instalação local antes de subir Phoenix Engine/Aviary. A assinatura das PHASE7K/7L prova a autenticidade do artefato de release; PHASE7O prova que os arquivos críticos atualmente instalados ainda correspondem ao último build aceito.

A verificação é deliberadamente parcial e crítica, não um hash completo de todos os ~6 mil arquivos a cada boot.

## Fonte de verdade

Os hashes esperados são gerados no build e armazenados em `release_build_manifest.json` na seção `startup_integrity`. A policy que define o conjunto crítico é `startup_integrity_policy.json`, cujo SHA-256 também é pinado na provenance.

`data/startup_integrity_cache.json` é apenas cache de performance. Ele nunca fornece hashes esperados e não entra em releases.

## Conjunto crítico

### SHA-256 em todo startup

Arquivos pequenos de controle e segurança, incluindo Kernel/API, launchers, updater, migration/signing/release policies e o próprio verifier de integridade.

### SHA-256 com cache/TTL

Artefatos pesados ou compilados, incluindo `platform_source/dist/server.cjs`, `bin/phoenix_sd_bridge.dll` e, no perfil `windows-ready`, o bundle Phoenix Llama Runtime.

O cache só é reutilizado quando `build_id`, SHA esperado, tamanho e `mtime_ns` coincidem e a certificação anterior ainda está dentro do TTL. Qualquer mudança de metadata ou expiração do TTL força hash completo. O TTL padrão é 24 horas e pode ser sobrescrito por `PHOENIX_STARTUP_INTEGRITY_CACHE_SECONDS`.

## Startup gate

`Iniciar_Phoenix.bat` executa recovery da PHASE7N primeiro. Depois que existe Python/venv válido, executa `startup_integrity.py verify`. Falha de integridade bloqueia o startup antes de storage, reparos de runtime ou API.

Uma árvore source/dev sem `release_build_manifest.json` e sem `data/update_release_state.json` continua permitida como `untracked`. Se um build foi aceito no estado monotônico de update, ausência de provenance ou `build_id` divergente é erro fatal.

## Upgrade e recovery

Depois de overlay, migrations, smoke e commit de release-state, o updater executa `startup_integrity.py verify --refresh`. A transação só chega a `committed` após essa certificação. Recovery de transação interrompida também exige o checkpoint `startup_integrity_complete` antes de finalizar.

## Comando manual

```bat
Verificar_Integridade_Phoenix.bat
```

Usa cache normal.

```bat
Verificar_Integridade_Phoenix.bat REFRESH
```

Força SHA-256 completo inclusive dos arquivos pesados.

## Segurança e limites

PHASE7O detecta corrupção e edição inesperada da instalação. Ela não substitui assinatura de release, trust-store, anti-rollback ou controles do sistema operacional. Um administrador local malicioso que possa alterar simultaneamente launcher, verifier e estado local está fora do modelo de ameaça desta camada. Para autenticidade de distribuição, use `signature_mode=required` das PHASE7K/7L.

## Estado local

`data/startup_integrity_cache.json` é:

- protegido pelo updater;
- proibido em release pública;
- descartável/reconstruível;
- não usado como fonte de verdade criptográfica.
