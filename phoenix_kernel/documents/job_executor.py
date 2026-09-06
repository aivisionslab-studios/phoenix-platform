"""Phoenix Document Pipeline V2 - Fase 7: Job Planner / Executor.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois de fechar a
Fase 6): até aqui o Python aprendeu a ler, estruturar, normalizar,
encontrar candidatos, agrupar em records e avaliar evidência. Esta fase
faz o Python aprender a PLANEJAR o trabalho - transformar um `JobPlan`
(Fase 1) + a lista de `Record`s (Fase 5) num conjunto de `Task`s (Fase 7,
`normalized.py`) pequenas e determinísticas, e executá-las com controle de
status, dependências, retry e checkpoint/resume.

Continua Python puro, ZERO LLM/OCR/visão - mesma regra de todas as fases
anteriores. Este módulo em si NUNCA chama LLM; quem chama (se precisar) é
a função `run_fn` que o CALLER injeta em `execute_task`/`run_pending_tasks`
- e uma falha dentro de `run_fn` (LLM fora do ar, por exemplo) vira uma
`Task` `FAILED` isolada, nunca uma exceção que derruba as outras tarefas
("Esse será o primeiro passo concreto pro objetivo maior: Python garante o
trabalho; a IA entra só quando uma tarefa explicitamente precisa dela" -
palavras do usuário).

Regra central pedida explicitamente pelo usuário: "Task não é Chunk". Uma
tarefa nunca é `chunk_01`/`chunk_02` - a identidade é semântica/
operacional: `task_id = f"task_{record_id}_{operation}"`, sempre estável
entre execuções do MESMO job (ver `Task` em `normalized.py`).

As cinco responsabilidades pedidas, cada uma com uma função própria aqui:
  1. criar tarefas determinísticas a partir do `JobPlan` -
     `create_tasks_from_job_plan`.
  2. controlar `PENDING/PROCESSING/DONE/FAILED/SKIPPED` (reaproveita
     `RecordStatus`, já definido desde a Fase 1 - não inventa um
     vocabulário novo) - `execute_task`/`run_pending_tasks`.
  3. dependências entre tarefas - `task_is_ready` (hoje sempre `True` na
     prática, ver limitação abaixo).
  4. retry controlado (`max_attempts`) - `execute_task`.
  5. checkpoint/resume - `merge_with_previous_state` (compara contra um
     `JobState.tasks` de uma execução anterior, tipicamente lido de um
     JSON salvo em disco via `JobState.to_json()`/`from_json()`).

Idempotência (pedida explicitamente): `compute_input_hash` gera um hash
estável a partir do que uma tarefa REALMENTE consome (blocos do record,
candidatos referenciados, e opcionalmente o status/valor da Fase 6 pra
esse record) - nunca de um campo "cosmético" como a `confidence` heurística
do Segmenter. `merge_with_previous_state` usa esse hash pra decidir: mesma
entrada + tarefa já `DONE` -> reaproveita sem executar de novo; entrada
diferente -> a tarefa volta a ser executável, mesmo que já tivesse rodado
antes.

Este módulo deliberadamente NÃO escreve nenhum XLSX/saída final - produz
só `Task`s executadas e seus resultados (via `run_fn`, decidido por quem
chama). Escrever a saída definitiva continua sendo trabalho de uma fase
posterior.

Limitações desta primeira versão, documentadas de propósito:
  - `create_tasks_from_job_plan` cria exatamente UMA tarefa por `Record`
    (a mesma `operation` do `JobPlan` pra todas) - o campo `dependencies`
    existe e é respeitado por `task_is_ready`, mas nenhuma tarefa criada
    aqui tem dependência nenhuma ainda (reservado pro dia em que um job
    precisar de um pipeline de várias etapas por record, ex: exemplo do
    usuário `task_r0042_extract` -> `_map` -> `_validate` -> `_write`).
  - `output_hash` é só o hash do RESULTADO devolvido por `run_fn` (via
    `json.dumps` com `default=str`) - não impõe nenhum formato particular
    de resultado; se `run_fn` devolver algo não serializável de jeito
    nenhum, o hash cai pra `None` sem quebrar a execução.
  - Checkpoint em disco (ler/escrever o JSON de `JobState` num arquivo,
    inclusive num disco dedicado como já discutido pro checkpoint da
    Fase 1) fica por conta de quem chama este módulo - aqui só existe a
    serialização em memória (`JobState.to_json()`/`from_json()`); este
    módulo nunca abre um arquivo sozinho."""
from __future__ import annotations

import hashlib
import json
from typing import Callable, Optional

from phoenix_kernel.documents.evidence_engine import FieldEvidence
from phoenix_kernel.documents.normalized import Candidate, JobPlan, JobState, Record, RecordStatus, Task


def _stable_hash(value: object) -> Optional[str]:
    """Hash sha256 estável de uma estrutura JSON-serializável -
    `sort_keys=True` garante que a MESMA informação sempre produz o MESMO
    hash, independente da ordem de inserção de um dict. Devolve `None`
    (nunca lança exceção) se `value` não for serializável de jeito
    nenhum - um resultado "estranho" de `run_fn` não pode derrubar a
    execução."""
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_input_hash(
    record: Record,
    candidates_by_id: dict[str, Candidate],
    field_evidences: Optional[list[FieldEvidence]] = None,
) -> str:
    """O hash de ENTRADA de uma tarefa - muda se, e só se, algo que a
    tarefa realmente consome mudar: os blocos do record, os candidatos
    referenciados (valor bruto/normalizado/validade), e opcionalmente o
    resultado da Fase 6 pra esse record (status/valor de cada campo).
    Nunca usa um campo heurístico/cosmético (ex: `Record.confidence`, que
    é só a estimativa do Segmenter, não algo que uma tarefa "processa")."""
    candidate_rows = []
    for candidate_id in record.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            continue
        candidate_rows.append({
            "id": candidate_id,
            "field_type": candidate.field_type,
            "raw_value": candidate.raw_value,
            "normalized_value": candidate.normalized_value,
            "valid": candidate.valid,
        })
    candidate_rows.sort(key=lambda row: row["id"])

    payload: dict = {
        "block_ids": list(record.block_ids),
        "candidates": candidate_rows,
    }
    if field_evidences is not None:
        evidence_rows = sorted(
            (
                {"field_type": fe.field_type, "status": fe.status, "value": fe.value}
                for fe in field_evidences
            ),
            key=lambda row: row["field_type"],
        )
        payload["evidence"] = evidence_rows

    result = _stable_hash(payload)
    assert result is not None  # payload aqui é sempre JSON-serializável (só str/float/int/bool/list/dict)
    return result


def create_tasks_from_job_plan(
    job_plan: JobPlan,
    records: list[Record],
    candidates_by_id: dict[str, Candidate],
    evidence_by_record: Optional[dict[str, list[FieldEvidence]]] = None,
    operation: Optional[str] = None,
) -> list[Task]:
    """Ponto de entrada principal da Fase 7: UMA `Task` determinística por
    `Record` - nunca "todos de uma vez", nunca um chunk de caracteres.
    `task_id` estável (`task_{record_id}_{operation}`) - rodar isto duas
    vezes pro MESMO job produz exatamente os MESMOS `task_id`s, o que é o
    que torna `merge_with_previous_state` (checkpoint/resume) possível."""
    op = operation or job_plan.operation
    tasks: list[Task] = []
    for record in records:
        field_evidences = (evidence_by_record or {}).get(record.record_id)
        tasks.append(Task(
            task_id=f"task_{record.record_id}_{op}",
            job_id=job_plan.job_id,
            record_id=record.record_id,
            operation=op,
            status=RecordStatus.PENDING,
            dependencies=[],
            attempts=0,
            input_hash=compute_input_hash(record, candidates_by_id, field_evidences),
            output_hash=None,
        ))
    return tasks


def task_is_ready(task: Task, tasks_by_id: dict[str, Task]) -> bool:
    """Uma tarefa só está pronta pra rodar quando TODAS as suas
    `dependencies` já estão `DONE`. Hoje `create_tasks_from_job_plan`
    nunca cria dependência nenhuma, então isto é sempre `True` na
    prática - pronto pro dia em que um job precisar de mais de uma
    operação encadeada por record (ver limitação no docstring do
    módulo)."""
    return all(
        dep_id in tasks_by_id and tasks_by_id[dep_id].status == RecordStatus.DONE
        for dep_id in task.dependencies
    )


def merge_with_previous_state(new_tasks: list[Task], previous_tasks_by_id: dict[str, Task]) -> list[Task]:
    """O mecanismo de CHECKPOINT/RESUME pedido explicitamente pelo
    usuário - compara cada tarefa recém-planejada (`new_tasks`, saída de
    `create_tasks_from_job_plan`, sempre `PENDING`/`attempts=0`) com a
    versão anterior de MESMO `task_id` (de uma execução anterior,
    tipicamente `previous_job_state.tasks`):
      - não existe versão anterior -> tarefa nova, fica como veio
        (`PENDING`).
      - existe, `input_hash` é o MESMO, e ela já estava `DONE`/`SKIPPED`
        -> a entrada não mudou e o resultado anterior continua válido -
        REAPROVEITA (`status`/`output_hash`/`attempts` da versão
        anterior) - "reinicia o Phoenix -> retoma da task 117 -> não
        refaz 1-116".
      - existe, `input_hash` é o MESMO, mas ela estava `FAILED` -> mantém
        `attempts` da versão anterior (o retry continua de onde parou,
        não reseta a contagem) - `max_attempts` em `execute_task` vale
        através de reinícios, não só dentro de uma execução.
      - existe, mas o `input_hash` MUDOU -> a entrada mudou de verdade
        desde a última vez; o resultado anterior não vale mais - fica
        `PENDING`/`attempts=0`, como uma tarefa efetivamente nova."""
    merged: list[Task] = []
    for task in new_tasks:
        previous = previous_tasks_by_id.get(task.task_id)
        if previous is None or previous.input_hash != task.input_hash:
            merged.append(task)
            continue
        if previous.status in (RecordStatus.DONE, RecordStatus.SKIPPED):
            merged.append(Task(
                task_id=task.task_id, job_id=task.job_id, record_id=task.record_id,
                operation=task.operation, status=previous.status, dependencies=task.dependencies,
                attempts=previous.attempts, input_hash=task.input_hash, output_hash=previous.output_hash,
            ))
        elif previous.status == RecordStatus.FAILED:
            merged.append(Task(
                task_id=task.task_id, job_id=task.job_id, record_id=task.record_id,
                operation=task.operation, status=RecordStatus.FAILED, dependencies=task.dependencies,
                attempts=previous.attempts, input_hash=task.input_hash, output_hash=previous.output_hash,
            ))
        else:
            # PROCESSING/PENDING anterior (ex: Phoenix caiu no meio da
            # execução) - trata como se nunca tivesse rodado, sem herdar
            # tentativa nenhuma; é seguro reexecutar do zero.
            merged.append(task)
    return merged


def execute_task(task: Task, run_fn: Callable[[Task], object], *, max_attempts: int = 3) -> Task:
    """Executa UMA tarefa, com a lógica de idempotência/retry pedida
    explicitamente:
      - já `DONE`/`SKIPPED` -> devolve como está, NÃO chama `run_fn`
        (reaproveitamento decidido antes, por `merge_with_previous_state`).
      - `FAILED` e já bateu `max_attempts` -> desiste, devolve como está
        (retry CONTROLADO, nunca infinito).
      - dependências não satisfeitas -> devolve como está, sem executar
        e SEM contar como tentativa (`task_is_ready`).
      - senão, chama `run_fn(task)`: sucesso -> `DONE` +
        `output_hash` do resultado, `attempts+1`; QUALQUER exceção
        (LLM fora do ar, erro de rede, bug no `run_fn`) -> `FAILED`,
        `attempts+1` - a exceção NUNCA propaga pra fora daqui, de
        propósito, pra uma falha nesta tarefa nunca impedir as outras
        (ver `run_pending_tasks`) - "LLM indisponível não pode impedir
        tasks puramente Python de continuarem"."""
    if task.status in (RecordStatus.DONE, RecordStatus.SKIPPED):
        return task
    if task.status == RecordStatus.FAILED and task.attempts >= max_attempts:
        return task

    try:
        result = run_fn(task)
    except Exception:
        return Task(
            task_id=task.task_id, job_id=task.job_id, record_id=task.record_id, operation=task.operation,
            status=RecordStatus.FAILED, dependencies=task.dependencies, attempts=task.attempts + 1,
            input_hash=task.input_hash, output_hash=task.output_hash,
        )

    return Task(
        task_id=task.task_id, job_id=task.job_id, record_id=task.record_id, operation=task.operation,
        status=RecordStatus.DONE, dependencies=task.dependencies, attempts=task.attempts + 1,
        input_hash=task.input_hash, output_hash=_stable_hash(result),
    )


def run_pending_tasks(tasks: list[Task], run_fn: Callable[[Task], object], *, max_attempts: int = 3) -> list[Task]:
    """Roda uma LISTA de tarefas, na ordem dada, cada uma via
    `execute_task` - uma falha numa tarefa NUNCA impede as seguintes de
    rodarem ("falha na task 117 -> 116 continuam DONE -> 117 FAILED ->
    118+ não perdem estado", pedido explícito do usuário). Devolve uma
    NOVA lista de `Task`s já atualizadas, na MESMA ordem de entrada -
    nunca reordena.

    Uma única PASSADA, na ordem dada: se uma dependência aparece ANTES na
    lista, ela já está `DONE` a tempo de liberar a tarefa seguinte na
    MESMA chamada; se aparece DEPOIS (ou só numa chamada futura), a
    tarefa dependente fica `PENDING` sem executar nesta passada - nunca
    reordena a lista nem faz uma segunda passada pra "esperar" uma
    dependência que ainda vai vir. Quem chama decide a ordem (hoje,
    `create_tasks_from_job_plan` não cria dependência nenhuma, então isto
    não importa na prática ainda)."""
    tasks_by_id = {t.task_id: t for t in tasks}
    updated: list[Task] = []
    for task in tasks:
        current = tasks_by_id[task.task_id]
        if not task_is_ready(current, tasks_by_id):
            updated.append(current)
            continue
        result = execute_task(current, run_fn, max_attempts=max_attempts)
        tasks_by_id[task.task_id] = result
        updated.append(result)
    return updated


def apply_tasks_to_job_state(job_state: JobState, tasks: list[Task]) -> JobState:
    """Grava o resultado de uma rodada de execução de volta no
    `JobState` (mutando `job_state.tasks` e devolvendo o mesmo objeto,
    pra encadear com `job_state.to_json()` e persistir o checkpoint em
    disco - decisão de ONDE gravar fica com quem chama, ver limitação no
    docstring do módulo)."""
    for task in tasks:
        job_state.tasks[task.task_id] = task
    return job_state
