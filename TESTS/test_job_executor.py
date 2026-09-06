"""Testes da Fase 7 do "Document Pipeline V2" (phoenix_kernel/documents/
job_executor.py) - Job Planner/Executor: cria `Task`s determinísticas por
`Record` (Fase 5) a partir de um `JobPlan` (Fase 1), executa com controle
de status/retry, e resolve checkpoint/resume via `input_hash`. Ver PHX-NEW
no topo daquele arquivo pro contexto e princípios completos (zero LLM;
"Task não é Chunk"; uma falha nunca derruba as outras tarefas).

Os cenários abaixo são exatamente os exigidos pelo usuário ao aprovar a
Fase 7."""
from __future__ import annotations

import pytest

from phoenix_kernel.documents.job_executor import (
    apply_tasks_to_job_state,
    compute_input_hash,
    create_tasks_from_job_plan,
    execute_task,
    merge_with_previous_state,
    run_pending_tasks,
    task_is_ready,
)
from phoenix_kernel.documents.normalized import (
    Candidate,
    JobMapping,
    JobPlan,
    JobSource,
    JobState,
    JobStrategy,
    JobTarget,
    Record,
    RecordStatus,
    Task,
)


def _job_plan(job_id: str = "job_001") -> JobPlan:
    return JobPlan(
        job_id=job_id,
        operation="map_record_to_target",
        sources=[JobSource(document_id="doc1")],
        target=JobTarget(type="xlsx", path="saida.xlsx"),
        mapping=JobMapping(columns=["ean", "price"]),
        strategy=JobStrategy(),
    )


def _record(record_id: str, candidate_ids: list[str] | None = None) -> Record:
    return Record(record_id=record_id, block_ids=[f"b_{record_id}"], candidate_ids=candidate_ids or [])


def _candidate(cid: str, field_type: str = "ean", raw_value: str = "123", normalized_value=None, valid: bool = True) -> Candidate:
    return Candidate(id=cid, field_type=field_type, raw_value=raw_value, block_id="b1",
                      normalized_value=normalized_value, valid=valid)


# ---------------------------------------------------------------------------
# criação de tarefas - identidade estável, uma por record
# ---------------------------------------------------------------------------

def test_two_hundred_records_produce_two_hundred_distinct_tasks():
    plan = _job_plan()
    records = [_record(f"r{i:04d}") for i in range(200)]
    tasks = create_tasks_from_job_plan(plan, records, {})

    assert len(tasks) == 200
    assert len({t.task_id for t in tasks}) == 200  # todos distintos


def test_task_id_is_stable_for_same_record_and_operation():
    """Rodar o planejamento do MESMO job duas vezes tem que produzir os
    MESMOS task_ids - é isso que torna checkpoint/resume possível."""
    plan = _job_plan()
    records = [_record("r0042")]
    first = create_tasks_from_job_plan(plan, records, {})
    second = create_tasks_from_job_plan(plan, records, {})

    assert first[0].task_id == second[0].task_id == "task_r0042_map_record_to_target"


def test_task_is_never_a_chunk_style_id():
    """"Task não é Chunk" - regra explícita do usuário: a identidade é
    record_id + operation, nunca um número sequencial de chunk."""
    plan = _job_plan()
    tasks = create_tasks_from_job_plan(plan, [_record("r0007")], {})
    assert "chunk" not in tasks[0].task_id
    assert tasks[0].task_id.startswith("task_r0007_")


def test_new_task_starts_pending_with_zero_attempts():
    plan = _job_plan()
    tasks = create_tasks_from_job_plan(plan, [_record("r0001")], {})
    assert tasks[0].status == RecordStatus.PENDING
    assert tasks[0].attempts == 0
    assert tasks[0].dependencies == []


# ---------------------------------------------------------------------------
# execução - falha isola, não derruba as outras
# ---------------------------------------------------------------------------

def test_task_failure_does_not_stop_or_corrupt_other_tasks():
    """Cenário exigido: falha na task 117 -> 116 continuam DONE -> 117
    FAILED -> 118+ não perdem estado (continuam sendo tentadas/DONE)."""
    plan = _job_plan()
    records = [_record(f"r{i:04d}") for i in range(200)]
    tasks = create_tasks_from_job_plan(plan, records, {})

    def run_fn(task: Task):
        if task.record_id == "r0117":
            raise RuntimeError("falha simulada só nesta tarefa")
        return {"ok": True, "record_id": task.record_id}

    results = run_pending_tasks(tasks, run_fn)
    by_record = {t.record_id: t for t in results}

    assert by_record["r0000"].status == RecordStatus.DONE
    assert by_record["r0116"].status == RecordStatus.DONE
    assert by_record["r0117"].status == RecordStatus.FAILED
    assert by_record["r0117"].attempts == 1
    assert by_record["r0118"].status == RecordStatus.DONE
    assert by_record["r0199"].status == RecordStatus.DONE
    assert len(results) == 200  # nenhuma tarefa "sumiu"


def test_llm_unavailable_does_not_block_pure_python_tasks():
    """Cenário exigido explicitamente: uma tarefa que dependeria de LLM
    (indisponível, simulado por uma exceção) não pode impedir tarefas
    puramente Python de continuar rodando e chegando a DONE."""
    plan = _job_plan()
    records = [_record("r_llm"), _record("r_python_1"), _record("r_python_2")]
    tasks = create_tasks_from_job_plan(plan, records, {})

    def run_fn(task: Task):
        if task.record_id == "r_llm":
            raise ConnectionError("LLM indisponível")
        return "resultado puro-python"

    results = run_pending_tasks(tasks, run_fn)
    by_record = {t.record_id: t for t in results}

    assert by_record["r_llm"].status == RecordStatus.FAILED
    assert by_record["r_python_1"].status == RecordStatus.DONE
    assert by_record["r_python_2"].status == RecordStatus.DONE


# ---------------------------------------------------------------------------
# retry controlado
# ---------------------------------------------------------------------------

def test_retry_gives_up_after_max_attempts():
    plan = _job_plan()
    tasks = create_tasks_from_job_plan(plan, [_record("r0001")], {})

    def always_fails(task: Task):
        raise RuntimeError("sempre falha")

    task = tasks[0]
    for _ in range(5):
        task = execute_task(task, always_fails, max_attempts=3)

    assert task.status == RecordStatus.FAILED
    assert task.attempts == 3  # nunca passa de max_attempts, mesmo chamando mais vezes


# ---------------------------------------------------------------------------
# dependências
# ---------------------------------------------------------------------------

def test_dependencies_block_task_until_satisfied():
    upstream = Task(task_id="task_r1_extract", job_id="job_001", record_id="r1", operation="extract")
    downstream = Task(task_id="task_r1_map", job_id="job_001", record_id="r1", operation="map",
                       dependencies=["task_r1_extract"])
    tasks_by_id = {upstream.task_id: upstream, downstream.task_id: downstream}

    assert task_is_ready(downstream, tasks_by_id) is False

    tasks_by_id[upstream.task_id] = Task(**{**upstream.__dict__, "status": RecordStatus.DONE})
    assert task_is_ready(downstream, tasks_by_id) is True


def test_run_pending_tasks_resolves_dependency_within_the_same_pass_when_ordered_first():
    """`run_pending_tasks` processa a lista em UMA passada, na ordem
    dada, atualizando o status conforme vai - então uma dependência que
    vem ANTES na lista já fica satisfeita a tempo da tarefa seguinte na
    MESMA chamada (útil pro dia em que um pipeline extract->map->
    validate->write do mesmo record for criado nesta ordem)."""
    upstream = Task(task_id="task_r1_extract", job_id="job_001", record_id="r1", operation="extract")
    downstream = Task(task_id="task_r1_map", job_id="job_001", record_id="r1", operation="map",
                       dependencies=["task_r1_extract"])

    results = run_pending_tasks([upstream, downstream], lambda task: "ok")
    by_id = {t.task_id: t for t in results}

    assert by_id["task_r1_extract"].status == RecordStatus.DONE
    assert by_id["task_r1_map"].status == RecordStatus.DONE


def test_run_pending_tasks_leaves_task_pending_when_dependency_comes_later_in_the_list():
    """O inverso do teste acima: `run_pending_tasks` NÃO faz múltiplas
    passadas nem reordena - se a dependência aparece DEPOIS na lista (ou
    numa chamada futura), a tarefa dependente fica `PENDING`, sem
    executar, até a dependência estar `DONE` numa passada anterior."""
    upstream = Task(task_id="task_r1_extract", job_id="job_001", record_id="r1", operation="extract")
    downstream = Task(task_id="task_r1_map", job_id="job_001", record_id="r1", operation="map",
                       dependencies=["task_r1_extract"])

    calls = []

    def run_fn(task: Task):
        calls.append(task.task_id)
        return "ok"

    # downstream ANTES de upstream na lista - a dependência ainda não
    # está DONE quando a vez dela chega nesta mesma passada.
    results = run_pending_tasks([downstream, upstream], run_fn)
    by_id = {t.task_id: t for t in results}

    assert by_id["task_r1_map"].status == RecordStatus.PENDING
    assert "task_r1_map" not in calls  # nunca chegou a ser executada
    assert by_id["task_r1_extract"].status == RecordStatus.DONE  # essa sim rodou


# ---------------------------------------------------------------------------
# idempotência / checkpoint / resume
# ---------------------------------------------------------------------------

def test_unchanged_input_reuses_previous_result_without_rerunning():
    plan = _job_plan()
    candidates_by_id = {"c1": _candidate("c1", normalized_value="123")}
    record = _record("r0032", ["c1"])

    tasks = create_tasks_from_job_plan(plan, [record], candidates_by_id)
    calls = []

    def run_fn(task: Task):
        calls.append(task.task_id)
        return "resultado"

    first_run = run_pending_tasks(tasks, run_fn)
    assert len(calls) == 1
    assert first_run[0].status == RecordStatus.DONE

    # simula reinício: replaneja do zero (mesmos records/candidatos) e
    # funde com o estado anterior antes de rodar de novo
    replanned = create_tasks_from_job_plan(plan, [record], candidates_by_id)
    previous_by_id = {t.task_id: t for t in first_run}
    merged = merge_with_previous_state(replanned, previous_by_id)
    second_run = run_pending_tasks(merged, run_fn)

    assert len(calls) == 1  # run_fn NÃO foi chamado de novo
    assert second_run[0].status == RecordStatus.DONE
    assert second_run[0].output_hash == first_run[0].output_hash


def test_changed_input_forces_task_to_rerun():
    plan = _job_plan()
    record = _record("r0032", ["c1"])

    tasks_v1 = create_tasks_from_job_plan(plan, [record], {"c1": _candidate("c1", normalized_value="123")})
    calls = []

    def run_fn(task: Task):
        calls.append(task.task_id)
        return "resultado"

    run_v1 = run_pending_tasks(tasks_v1, run_fn)
    assert len(calls) == 1

    # o candidato mudou de valor (documento reprocessado com novo dado)
    tasks_v2 = create_tasks_from_job_plan(plan, [record], {"c1": _candidate("c1", normalized_value="456")})
    assert tasks_v2[0].input_hash != tasks_v1[0].input_hash

    previous_by_id = {t.task_id: t for t in run_v1}
    merged = merge_with_previous_state(tasks_v2, previous_by_id)
    assert merged[0].status == RecordStatus.PENDING  # entrada mudou -> não reaproveita

    run_v2 = run_pending_tasks(merged, run_fn)
    assert len(calls) == 2  # run_fn FOI chamado de novo
    assert run_v2[0].status == RecordStatus.DONE


def test_resume_after_restart_does_not_redo_already_done_tasks():
    """Cenário exigido: reinicia o Phoenix -> retoma da task que falhou
    -> não refaz as que já estavam DONE."""
    plan = _job_plan()
    records = [_record(f"r{i:04d}") for i in range(200)]
    tasks = create_tasks_from_job_plan(plan, records, {})

    def failing_run_fn(task: Task):
        if task.record_id == "r0117":
            raise RuntimeError("falha - Phoenix vai 'cair' logo depois")
        return "ok"

    first_run = run_pending_tasks(tasks, failing_run_fn)
    assert {t.record_id: t.status for t in first_run}["r0117"] == RecordStatus.FAILED

    # "reinicia": replaneja do zero e funde com o estado anterior
    replanned = create_tasks_from_job_plan(plan, records, {})
    previous_by_id = {t.task_id: t for t in first_run}
    merged = merge_with_previous_state(replanned, previous_by_id)

    calls = []

    def run_fn_after_restart(task: Task):
        calls.append(task.record_id)
        return "ok"

    second_run = run_pending_tasks(merged, run_fn_after_restart)

    # só a que tinha falhado (e continua PENDING/FAILED) é reexecutada
    assert calls == ["r0117"]
    by_record = {t.record_id: t for t in second_run}
    assert by_record["r0000"].status == RecordStatus.DONE
    assert by_record["r0117"].status == RecordStatus.DONE
    assert by_record["r0117"].attempts == 2  # 1 da primeira tentativa + 1 depois do resume


# ---------------------------------------------------------------------------
# JobState / checkpoint em JSON
# ---------------------------------------------------------------------------

def test_apply_tasks_to_job_state_and_json_roundtrip_preserves_tasks():
    plan = _job_plan()
    tasks = create_tasks_from_job_plan(plan, [_record("r0001"), _record("r0002")], {})
    executed = run_pending_tasks(tasks, lambda task: "ok")

    job_state = JobState(job_id=plan.job_id)
    apply_tasks_to_job_state(job_state, executed)

    restored = JobState.from_json(job_state.to_json())
    assert set(restored.tasks.keys()) == {t.task_id for t in executed}
    assert all(t.status == RecordStatus.DONE for t in restored.tasks.values())


def test_compute_input_hash_incorporates_evidence_status_when_given():
    from phoenix_kernel.documents.evidence_engine import FieldEvidence

    record = _record("r1", ["c1"])
    candidates_by_id = {"c1": _candidate("c1", normalized_value="123")}
    evidence_a = [FieldEvidence(field_type="ean", record_id="r1", status="probable", value="123")]
    evidence_b = [FieldEvidence(field_type="ean", record_id="r1", status="confirmed", value="123")]

    hash_a = compute_input_hash(record, candidates_by_id, evidence_a)
    hash_b = compute_input_hash(record, candidates_by_id, evidence_b)
    hash_none = compute_input_hash(record, candidates_by_id, None)

    assert hash_a != hash_b  # status de evidência diferente -> hash diferente
    assert hash_none not in (hash_a, hash_b)  # ausência de evidência é seu próprio caso


def test_compute_input_hash_is_stable_for_identical_input():
    record = _record("r1", ["c1", "c2"])
    candidates_by_id = {
        "c1": _candidate("c1", normalized_value="123"),
        "c2": _candidate("c2", field_type="price", raw_value="10,00", normalized_value=10.0),
    }
    assert compute_input_hash(record, candidates_by_id) == compute_input_hash(record, candidates_by_id)
