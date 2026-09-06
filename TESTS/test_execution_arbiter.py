from phoenix_kernel.orchestration.execution_arbiter import (
    ClaimState, ExecutionArbiter, ResourcePolicy,
)


def test_unknown_route_is_explicit_passthrough():
    a = ExecutionArbiter()
    d = a.preflight_path('/api/state', 'GET')
    assert d.claim == ClaimState.NOT_CLAIMED
    assert d.legacy_allowed is True
    assert d.resource_policy == ResourcePolicy.LEGACY


def test_chat_is_cpu():
    d = ExecutionArbiter().intercept('Olá, converse comigo')
    assert d.claimed
    assert d.intent == 'chat'
    assert d.resource_policy == ResourcePolicy.CPU


def test_image_generation_is_gpu():
    d = ExecutionArbiter().intercept('gere uma imagem de uma fênix')
    assert d.intent == 'image_generation'
    assert d.resource_policy == ResourcePolicy.GPU


def test_english_selected_sdxl_command_is_image_generation() -> None:
    d = ExecutionArbiter().intercept(
        'Generate an image using the selected SDXL model: an ancient observatory, cinematic lighting'
    )
    assert d.claimed
    assert d.intent == 'image_generation'
    assert d.executor == 'image_pipeline'
    assert d.resource_policy == ResourcePolicy.GPU


def test_english_question_about_image_generation_stays_chat() -> None:
    d = ExecutionArbiter().intercept('How do I generate an image with Vulkan?')
    assert d.intent == 'chat'
    assert d.resource_policy == ResourcePolicy.CPU


def test_raw_stable_diffusion_prompt_is_gpu():
    d = ExecutionArbiter().intercept(
        'A majestic phoenix made of crimson and golden fire rising from dark volcanic ashes, '
        'enormous detailed wings fully open, glowing embers floating through the air, '
        'dramatic cinematic lighting, highly detailed feathers, sharp focus, concept art, '
        'volumetric lighting, masterpiece'
    )
    assert d.claimed
    assert d.intent == 'image_generation'
    assert d.executor == 'image_pipeline'
    assert d.resource_policy == ResourcePolicy.GPU


def test_question_about_image_generation_stays_chat():
    d = ExecutionArbiter().intercept(
        'Como faço um prompt com cinematic lighting, sharp focus, concept art, masterpiece?'
    )
    assert d.intent == 'chat'
    assert d.resource_policy == ResourcePolicy.CPU


def test_document_create_phoenix_self_is_grounded_and_gpu_fallback():
    d = ExecutionArbiter().intercept(
        'Crie um documento TXT sobre os recursos atuais da Phoenix Engine',
        requested_operation='create', output_format='txt', unlimited_output=True,
    )
    assert d.intent == 'document_create'
    assert d.subject == 'phoenix_self'
    assert d.grounding == 'internal_project_state'
    assert d.resource_policy == ResourcePolicy.GPU_WITH_CPU_FALLBACK
    assert d.allows_cpu_fallback


def test_short_document_read_is_cpu():
    d = ExecutionArbiter().intercept(
        'resuma isto', attachments=['relatorio.pdf'], requested_operation='read', source_chars=2000,
    )
    assert d.intent == 'document_read'
    assert d.resource_policy == ResourcePolicy.CPU


def test_two_docs_one_xlsx_claims_fill_template():
    d = ExecutionArbiter().intercept(
        'preencha com os dados', attachments=['fonte.docx', 'modelo.xlsx']
    )
    assert d.intent == 'document_fill_template'
    assert d.resource_policy == ResourcePolicy.GPU_WITH_CPU_FALLBACK


def test_document_edit_heavy_gets_gpu_burst_policy():
    d = ExecutionArbiter().intercept(
        'corrija este documento', attachments=['a.docx'], requested_operation='edit', source_chars=9000,
    )
    assert d.intent == 'document_edit'
    assert d.resource_policy == ResourcePolicy.GPU_WITH_CPU_FALLBACK


def test_worker_policy_semantics_are_source_contract():
    from pathlib import Path
    text = (Path(__file__).parents[1] / 'phoenix_kernel/documents/document_llm_worker.py').read_text(encoding='utf-8')
    assert 'Execution Arbiter é a única autoridade' in text
    assert 'resource_policy:' in text
    assert 'Fallback CPU foi AUTORIZADO pela política recebida' in text
