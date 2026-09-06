from pathlib import Path

ROOT = Path(__file__).parents[1]

def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_sdxl_matches_validated_split():
    # PHX-FIX (31/08, corrigido de novo no mesmo dia): a versão anterior
    # deste teste exigia a AUSÊNCIA de "--clip-on-cpu" no perfil SDXL,
    # com a teoria de que o sd-cli desreferenciaria um ponteiro de
    # contexto CLIP não inicializado (SDXL carrega via "-m", sem
    # "--clip_l" separado em "components"). Essa teoria nunca foi
    # confirmada por um crash reproduzido de verdade no perfil
    # sdxl-checkpoint - e documentação externa do próprio usuário (guia
    # AIVisionsLab, seção 26, "SDXL 1024x1024 na RX 580 via Vulkan") traz
    # um comando de produção real e testado nesta mesma RX 580 usando
    # exatamente "-m sd_xl_base_1.0.safetensors --clip-on-cpu
    # --vae-on-cpu --vae-tiling", com imagem gerada com sucesso. A flag
    # funciona normalmente aplicada ao contexto CLIP interno do
    # checkpoint, mesmo sem um "--clip_l" externo. Restaurado pra exigir
    # a presença da flag, alinhado com o comando real validado.
    t = src("phoenix_kernel/runtime/drivers/sd_cpp.py")
    s = t.index('"name": "sdxl-checkpoint"')
    e = t.index("DEFAULT_PROFILE", s)
    b = t[s:e]
    assert '"--vae-on-cpu", "--clip-on-cpu", "--vae-tiling"]' in b

def test_global_gpu_only_flag_stripper_removed():
    assert "PHX-GPU-ONLY: nunca permitir offload explícito para CPU" not in src(
        "phoenix_kernel/runtime/drivers/sd_cpp.py"
    )

def test_prompt_passes_literal_to_plan():
    assert 'parameters={"prompt": prompt}' in src("phoenix_kernel/resident/resident_manager.py")

def test_cleanup_precedes_direct_vram_guard():
    t = src("phoenix_kernel/resident/resident_manager.py")
    s = t.index("async def generate_image_direct")
    prep = t.index('await self.runtime.prepare_exclusive("sdxl")', s)
    guard = t.index("await self._vram_guard(", prep)
    assert prep < guard

def test_llama_default_cpu():
    t = src("phoenix_kernel/runtime/drivers/llama_cpp.py")
    assert 'force_ngl: str | None = None' in t
    assert 'device: str | None = None' in t
    assert 'os.environ.get("PHOENIX_LLM_NGL", "0")' in t

def test_document_arbiter_cpu():
    t = src("phoenix_kernel/orchestration/execution_arbiter.py")
    s = t.index('if op in {"document_read"')
    e = t.index("table =", s)
    assert "resource = ResourcePolicy.CPU" in t[s:e]

def test_native_diffusion_process_isolated_and_trackable():
    t = src("phoenix_kernel/runtime/drivers/phoenix_diffusion.py")
    assert 'multiprocessing.get_context("spawn")' in t
    assert "self._process = process" in t
    assert "create_subprocess_exec" not in t
