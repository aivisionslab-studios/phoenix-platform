# Integração UI Phoenix/Aviary — aviso obrigatório de telemetria

Na primeira execução ou sempre que `notice_required=true`, a interface deve exibir o aviso retornado por `GET /api/telemetry/privacy-notice` antes de oferecer ativação.

Fluxo recomendado:
1. `GET /api/telemetry/status`.
2. Se `notice_required=true`, abrir modal não enganoso com `may_collect`, `never_collect_by_policy` e controles por categoria.
3. Oferecer `Ver preview` usando `GET /api/telemetry/preview`.
4. Ativar somente via `POST /api/telemetry/consent` com `accepted_notice_version` exatamente igual à versão mostrada.
5. Disponibilizar permanentemente `Revogar` -> `POST /api/telemetry/revoke`.
6. Não usar caixa pré-marcada, consentimento implícito ou ativação por atualização.
