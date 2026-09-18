# PHX-PHASE7C — Windows Ready Build/Release Command

Esta fase transforma o contrato das PHASE7A/7B em um único comando Windows de produção:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows_ready_release.ps1
```

Fluxo fail-closed:

1. `npm ci` quando necessário, `npm run lint`, `npm run build` e `node --check` para a Aviary.
2. Valida o bundle `bin/phoenix-llama-runtime/windows-x64`; se inválido, recompila/repara pelo source vendorizado.
3. Valida `bin/phoenix_sd_bridge.dll`; se inválida, recompila/repara Phoenix Diffusion.
4. Executa `verify_release_clean.py`.
5. Executa a suíte pytest completa por padrão.
6. Gera `windows-ready` em ZIP temporário.
7. Reabre o ZIP com `verify_release_archive.py`, valida CRC, manifest, paths proibidos e hashes do runtime.
8. Publica atomically somente após todas as etapas passarem.

O arquivo final padrão é:

`release_output/PHOENIX_4.5_WINDOWS_READY.zip`

`release_output/` é excluído por `.releaseignore` para impedir que uma release anterior seja empacotada dentro da próxima.

Flags:

- `-SkipTests`: uso excepcional; release oficial deve rodar testes.
- `-SkipNpmInstall`: reutiliza `node_modules` existente, mas ainda executa lint/build.

A execução fora do Windows falha imediatamente. A fase não fabrica binários Windows em ambientes não-Windows.
