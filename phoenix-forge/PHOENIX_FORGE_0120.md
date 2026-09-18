# Phoenix Forge 0.12.0 — Engine Gateway e validação de entrega

O Forge 0.12 fecha a integração de chat local com a Phoenix 4.5 R6.2.

- `/health/live`: liveness imediato, sem descoberta de hardware.
- `/health/ready`: estado completo de GPU/ledger com cache de 30 segundos.
- `/api/runtime/guarded-chat`: preserva resposta final e raciocínio em campos
  distintos, respeita o modo solicitado e executa as travas do ledger.
- Uma resposta vazia, truncada ou que contenha apenas raciocínio não é entregue.
- Após falhas repetidas da GPU, o controle CPU decide se o defeito pertence ao
  escopo da GPU; a decisão e o alerta retornam no envelope auditável.
