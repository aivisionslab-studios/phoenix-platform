# Phoenix 4.5 — Mapa de Testes (atualizado)

> **731 passed, 2 skipped** (`python -m pytest TESTS/ -q`, confirmado em 06/09/2026).
> PHX-NOTE: esse número reflete a suíte real na data acima. As tabelas
> abaixo cobrem em detalhe as rodadas de auditoria específicas já
> documentadas (Flux/RAG/modelos/áudio/planilhas da rodada de setembro, e
> a investigação de "resposta cortada" de 06/09 — ver
> [INVESTIGACAO_RESPOSTA_CORTADA.md](./INVESTIGACAO_RESPOSTA_CORTADA.md))
> — não é uma reauditoria linha-a-linha de toda a suíte a cada rodada.

> Última atualização: setembro/2026. Reflete todas as correções da sessão de auditoria (Flux removido, RAG sem dupla vetorização, detecção de modelos estável, TTS unificado, preenchimento determinístico, extração de nome por título numerado).


## O que mudou nesta rodada de auditoria

| Área | Correção | Teste que cobre |
|------|----------|-----------------|
| Imagem | Flux/SD3.5 removidos (crash 0xC0000005 na RX 580); SDXL default | `test_sd_cpp_backend_detection`, `test_rx580_validated_pipeline` |
| RAG | dupla vetorização eliminada (upsert único) | `test_rag_chunking_and_grouping` |
| Modelos | detecção intermitente: caminho absoluto + reload nos 2 resolvedores de storage | `test_aviary_provider_no_fake_models` |
| Áudio | texto→áudio unificado com o particionamento do audiolivro | `test_synthesize_speech_bridge` |
| Planilhas | preenchimento DETERMINÍSTICO (segundos, não 90min) + filtro de linhas fantasma | `test_pipeline_fill_route`, `test_pipeline_orchestrator` |
| Planilhas | nome de produto por título numerado ('63. Nome') → coluna Descrição | `test_candidate_engine`, `test_pipeline_orchestrator` |
| Fiscal/EAN | RAG fiscal (sugere NCM/CEST de base auditada) + busca de EAN com auditoria | `test_fiscal_rag`, `test_barcode_finder` |
| Planilhas | Smart Filler (regras + geração + guarda-fiscal) | `test_smart_filler` |


## Como validar

```bash
python -m pytest TESTS/ -q                                          # tudo (612 passed, 2 skipped)
python -m pytest TESTS/ -k "sd_cpp or diffusion or rx580"    -q     # imagem
python -m pytest TESTS/ -k "kokoro or whisper or synthesize" -q     # áudio
python -m pytest TESTS/ -k "candidate or segmenter or identity" -q  # pipeline docs
python -m pytest TESTS/ -k "fill or smart_filler or pipeline"  -q   # planilhas
python -m pytest TESTS/ -k "fiscal or barcode"               -q     # fiscal/EAN
python -m pytest TESTS/ -k "rag or chroma"                    -q     # RAG
```
Dependências de teste: `pip install pytest pytest-asyncio chromadb py3langid soundfile openpyxl python-docx`


## Índice por área

- 🖼️ Geração de Imagem (SD1.5/SDXL) — 41 testes
- 🎙️ Áudio (STT/TTS/Audiolivro) — 45 testes
- 📄 Pipeline de Documentos V2 — 215 testes
- 📊 Planilhas & Preenchimento — 76 testes
- 🏷️ Fiscal & Código de Barras — 10 testes
- 📚 RAG (base de conhecimento) — 41 testes
- 🧠 Raciocínio & Arbitragem — 72 testes
- 🔌 Drivers & Runtime — 34 testes
- 🖥️ Hardware & Telemetria — 9 testes
- 🌐 Modelos & Catálogo — 41 testes
- 🚀 Release & Higiene — 14 testes

---


## 🖼️ Geração de Imagem (SD1.5/SDXL)

*41 testes em 5 arquivo(s).*


### test_describe_image_bridge.py
**Módulo:** `phoenix_kernel.resident.resident_manager`

Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser contornado" — Seção 3 da diretiva de 20 seções). Achado: POST /api/describe-image em api_server.py resolvia o modelo de visão via resident.registry.resolve("vision") só pra citar no ExecutionPlan, mas exec…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_describe_image_direct_uses_resolved_model_and_tracks_it` | Describe image direct uses resolved model and tracks it |
| ☐ | `test_describe_image_direct_missing_file_fails_without_calling_runtime` | Describe image direct missing file fails without calling runtime |
| ☐ | `test_describe_image_direct_empty_path_fails_without_calling_runtime` | Describe image direct empty path fails without calling runtime |
| ☐ | `test_describe_image_direct_calls_vram_guard_with_correct_runtime_and_model` | _vram_guard precisa ser chamado com o runtime/modelo de visão resolvidos, por consistência com generate_image_direct (defesa em profundidade caso o dr… |
| ☐ | `test_real_vram_guard_does_not_unload_image_model_for_vision` | Regressão fim a fim do bug real (2026-08-28): com o _vram_guard de VERDADE (não mockado) e um modelo de imagem já rastreado como ativo, descrever uma … |
| ☐ | `test_describe_image_direct_runtime_failure_propagates_real_error` | Describe image direct runtime failure propagates real error |
| ☐ | `test_describe_image_route_calls_resident_not_runtime_execute_directly` | Describe image route calls resident not runtime execute directly |
| ☐ | `test_describe_image_route_surfaces_resident_error` | Describe image route surfaces resident error |
| ☐ | `test_describe_image_route_missing_resident_returns_error` | Describe image route missing resident returns error |
| ☐ | `test_describe_image_route_cleans_temp_file_even_on_error` | Describe image route cleans temp file even on error |


### test_gpu_only_exclusive_policy.py
**Módulo:** `phoenix_kernel.orchestration.execution_arbiter`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_resource_policy_is_differentiated_not_blanket_gpu` | Resource policy is differentiated not blanket gpu |
| ☐ | `test_exclusive_runtime_contract` | Exclusive runtime contract |


### test_phoenix_diffusion_native_wiring.py
**Módulo:** `phoenix_kernel.runtime.drivers.phoenix_diffusion`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_runtime_registers_native_phoenix_diffusion` | Runtime registers native phoenix diffusion |
| ☐ | `test_driver_has_no_cli_or_http_runtime` | Driver has no cli or http runtime |
| ☐ | `test_ctypes_abi_matches_public_header_shape` | Ctypes abi matches public header shape |
| ☐ | `test_fork_is_self_contained_and_installer_does_not_clone_old_runtime` | Fork is self contained and installer does not clone old runtime |
| ☐ | `test_launcher_repairs_missing_bridge_before_starting_api` | Launcher repairs missing bridge before starting api |
| ☐ | `test_missing_bridge_error_points_to_the_real_repair_entrypoint` | Missing bridge error points to the real repair entrypoint |
| ☐ | `test_flux_cli_compatibility_flags_are_translated_for_the_c_api` | Flux cli compatibility flags are translated for the c api |
| ☐ | `test_profile_without_cpu_aliases_keeps_automatic_placement` | Profile without cpu aliases keeps automatic placement |
| ☐ | `test_flux_ladder_contains_supported_cpu_gpu_hybrid_modes` | Flux ladder contains supported cpu gpu hybrid modes |
| ☐ | `test_manual_native_placement_disables_flux_ladder` | Manual native placement disables flux ladder |
| ☐ | `test_z_image_uses_modern_llm_abi_and_hybrid_fallback` | Z image uses modern llm abi and hybrid fallback |
| ☐ | `test_worker_exit_error_is_never_blank` | Worker exit error is never blank |
| ☐ | `test_model_change_restarts_the_isolated_worker` | Model change restarts the isolated worker |
| ☐ | `test_active_installer_and_knowledge_base_use_current_sd_cmake_option` | Active installer and knowledge base use current sd cmake option |
| ☐ | `test_image_pipeline_messages_are_not_attributed_to_the_chat_llm` | Image pipeline messages are not attributed to the chat llm |
| ☐ | `test_driver_name_and_version_are_phoenix_45` | Driver name and version are phoenix 45 |


### test_rx580_validated_pipeline.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_sdxl_matches_validated_split` | Sdxl matches validated split |
| ☐ | `test_global_gpu_only_flag_stripper_removed` | Global gpu only flag stripper removed |
| ☐ | `test_prompt_passes_literal_to_plan` | Prompt passes literal to plan |
| ☐ | `test_cleanup_precedes_direct_vram_guard` | Cleanup precedes direct vram guard |
| ☐ | `test_llama_default_cpu` | Llama default cpu |
| ☐ | `test_document_arbiter_cpu` | Document arbiter cpu |
| ☐ | `test_native_diffusion_process_isolated_and_trackable` | Native diffusion process isolated and trackable |


### test_sd_cpp_backend_detection.py
**Módulo:** `phoenix_kernel.runtime.drivers`

PHX-FIX (31/08, investigacao da RECORRENCIA do crash 0xC0000005 no flux1-schnell): o pytest nunca cobriu `_detect_has_rocm()`/`_detect_has_cuda()` em `sd_cpp.py` antes - por isso o patch anterior (que corrigiu só MODEL_PROFILES) passou 100% verde enquanto um bug diferente, no blo…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_hipconfig_no_longer_used_as_rocm_signal` | Hipconfig no longer used as rocm signal |
| ☐ | `test_detect_has_rocm_requires_nonempty_stdout` | Detect has rocm requires nonempty stdout |
| ☐ | `test_detect_has_rocm_rejects_known_polaris_gcn4_card` | Detect has rocm rejects known polaris gcn4 card |
| ☐ | `test_detect_has_rocm_accepts_real_modern_rocm_gpu` | Detect has rocm accepts real modern rocm gpu |
| ☐ | `test_detect_has_cuda_still_requires_nonempty_stdout` | Detect has cuda still requires nonempty stdout |
| ☐ | `test_offload_flags_survive_when_no_gpu_backend_detected` | Offload flags survive when no gpu backend detected |


## 🎙️ Áudio (STT/TTS/Audiolivro)

*45 testes em 6 arquivo(s).*


### test_audio_upload_consistency.py
**Módulo:** *(vários módulos)*

Testes de regressão pra auditoria 2026-08-20, "áudio no ChatView/Aviary" (frente aberta a pedido do usuário depois da Rodada 18, investigada por um agente com Playwright real - não só leitura de código). Dois achados reais: 1. `platform_source/src/components/aviary/ChatView.tsx` …


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_chatview_and_aviaryapp_use_the_same_audio_extension_set` | Chatview and aviaryapp use the same audio extension set |
| ☐ | `test_file_input_accept_attribute_includes_every_audio_extension_the_js_handles` | File input accept attribute includes every audio extension the js handles |
| ☐ | `test_backend_allows_every_audio_extension_the_frontend_routes_to_transcribe` | Backend allows every audio extension the frontend routes to transcribe |
| ☐ | `test_aac_specifically_is_allowed_end_to_end` | Aac specifically is allowed end to end |
| ☐ | `test_process_launcher_bar_no_longer_has_its_own_duplicate_audio_input` | Process launcher bar no longer has its own duplicate audio input |
| ☐ | `test_aviaryapp_no_longer_discards_user_text_after_audio_transcription` | Aviaryapp no longer discards user text after audio transcription |


### test_kokoro_gpu_install_option.py
**Módulo:** *(vários módulos)*

Teste de regressão pra um pedido real do usuário (2026-08-23): ele viu o audiolivro sintetizando em CPU pura (Gerenciador de Tarefas mostrando GPU em 2% e CPU em 50%) e perguntou "podemos pensar em rodar via gpu, nao?". Pesquisa real feita nesta sessão (lendo o código-fonte insta…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_tts_device_env_var_defaults_to_cpu` | Tts device env var defaults to cpu |
| ☐ | `test_common_ps1_branches_on_tts_device_env_var` | Common ps1 branches on tts device env var |
| ☐ | `test_gpu_path_installs_directml_and_uninstalls_plain_onnxruntime` | Gpu path installs directml and uninstalls plain onnxruntime |
| ☐ | `test_cpu_path_is_unchanged_default_behavior` | Cpu path is unchanged default behavior |
| ☐ | `test_requesting_gpu_outside_windows_falls_back_to_cpu_with_warning` | Requesting gpu outside windows falls back to cpu with warning |
| ☐ | `test_requirements_txt_documents_the_gpu_alternative` | Requirements txt documents the gpu alternative |
| ☐ | `test_kokoro_engine_logs_active_execution_providers` | Kokoro engine logs active execution providers |


### test_kokoro_synthesis_error_formatting.py
**Módulo:** `phoenix_kernel.runtime.drivers.kokoro_tts`

Teste de regressão pra um bug real achado nesta sessão (2026-08-23), ao testar o modo GPU (v49, onnxruntime-directml) na máquina real do usuário: TODOS os blocos de um audiolivro falharam na síntese, e o log mostrado pra ele foi: Bloco 0 falhou na síntese ('utf-8' codec can't dec…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_unicode_decode_error_gets_actionable_dml_explanation` | Unicode decode error gets actionable dml explanation |
| ☐ | `test_normal_exception_passes_through_unchanged` | Normal exception passes through unchanged |
| ☐ | `test_value_error_passes_through_unchanged` | Value error passes through unchanged |
| ☐ | `test_never_raises_even_if_str_itself_fails` | Never raises even if str itself fails |


### test_piper_removed.py
**Módulo:** `phoenix_kernel.runtime`

Teste pro achado real do usuário 2026-08-24: "se piper nao funciona e kokoro é melhor, jogar fora o piper de vez" - depois de eu explicar que o PiperDriver já estava morto no código (Kokoro assumiu como motor de voz padrão em 2026-08-23, sem nenhuma ponte real chamando `runtime="…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_piper_driver_file_deleted` | Piper driver file deleted |
| ☐ | `test_runtime_engine_no_longer_imports_or_registers_piper` | Runtime engine no longer imports or registers piper |
| ☐ | `test_runtime_engine_module_has_no_piper_driver_symbol` | Runtime engine module has no piper driver symbol |
| ☐ | `test_catalog_models_json_has_no_piper_runtime_entries` | Catalog models json has no piper runtime entries |
| ☐ | `test_catalog_voice_studio_no_longer_lists_piper_connector` | Catalog voice studio no longer lists piper connector |
| ☐ | `test_install_common_ps1_no_longer_downloads_piper_binary_or_voices` | Install common ps1 no longer downloads piper binary or voices |
| ☐ | `test_nothing_in_project_still_resolves_speech_synthesis_role` | Nothing in project still resolves speech synthesis role |


### test_synthesize_speech_bridge.py
**Módulo:** `phoenix_kernel.resident.resident_manager`

Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser contornado" — Seção 3 da diretiva de 20 seções), ATUALIZADO em 2026-08-23 pra refletir a troca do motor de voz padrão de Piper pra Kokoro-82M (pedido do usuário: "kokoro será motor pra transformar texto em…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_generate_speech_direct_uses_kokoro_and_tracks_it` | Generate speech direct uses kokoro and tracks it |
| ☐ | `test_generate_speech_direct_voice_hint_overrides_detection` | Um voice_hint explícito (ID de voz OU código de idioma) tem prioridade sobre a detecção automática - o usuário escolheu manualmente no seletor da UI, … |
| ☐ | `test_generate_speech_direct_empty_text_fails_without_calling_engine` | Generate speech direct empty text fails without calling engine |
| ☐ | `test_generate_speech_direct_engine_not_installed_returns_honest_error` | Generate speech direct engine not installed returns honest error |
| ☐ | `test_generate_speech_direct_synthesis_failure_propagates_real_error` | Generate speech direct synthesis failure propagates real error |
| ☐ | `test_synthesize_speech_route_calls_resident_not_runtime_execute_directly` | Synthesize speech route calls resident not runtime execute directly |
| ☐ | `test_synthesize_speech_route_empty_text_422_without_calling_resident` | Synthesize speech route empty text 422 without calling resident |
| ☐ | `test_synthesize_speech_route_surfaces_resident_error_as_422` | Synthesize speech route surfaces resident error as 422 |
| ☐ | `test_synthesize_speech_route_missing_resident_returns_503` | Synthesize speech route missing resident returns 503 |
| ☐ | `test_synthesize_speech_route_success_returns_base64_audio` | Synthesize speech route success returns base64 audio |
| ☐ | `test_synthesize_speech_route_missing_output_file_returns_500` | Synthesize speech route missing output file returns 500 |


### test_whisper_model_provisioning.py
**Módulo:** `phoenix_kernel.models.model_manager`

Teste de regressão pra auditoria 2026-08-20 ("Whisper model provisioning"). Achado real, confirmado numa instalação de produção (log real anexado pelo usuário): whisper.cpp compilava certinho (common.ps1 clona e builda), /api/transcribe existia e funcionava - mas NADA no provisio…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_downloads_catalog_has_whisper_base_entry` | Downloads catalog has whisper base entry |
| ☐ | `test_download_model_whisper_base_downloads_via_part_and_validates_size` | Download model whisper base downloads via part and validates size |
| ☐ | `test_download_model_rejects_empty_response_and_leaves_no_partial_file` | Download model rejects empty response and leaves no partial file |
| ☐ | `test_download_model_treats_existing_zero_byte_file_as_invalid_cache` | Download model treats existing zero byte file as invalid cache |
| ☐ | `test_download_model_reuses_valid_nonzero_cache_without_re_downloading` | Download model reuses valid nonzero cache without re downloading |
| ☐ | `test_ensure_default_stt_model_returns_true_when_valid_file_present` | Ensure default stt model returns true when valid file present |
| ☐ | `test_ensure_default_stt_model_triggers_background_download_when_missing` | Ensure default stt model triggers background download when missing |
| ☐ | `test_ensure_default_stt_model_redownloads_corrupted_small_file` | Ensure default stt model redownloads corrupted small file |
| ☐ | `test_whisper_driver_missing_model_error_shows_real_resolved_path` | Whisper driver missing model error shows real resolved path |
| ☐ | `test_whisper_driver_present_model_proceeds_past_the_model_check` | Whisper driver present model proceeds past the model check |


## 📄 Pipeline de Documentos V2

*215 testes em 11 arquivo(s).*


### test_candidate_engine.py
**Módulo:** `phoenix_kernel.documents.candidate_engine`

Testes da Fase 4 do "Document Pipeline V2" (phoenix_kernel/documents/ candidate_engine.py) - encontra candidatos de campo dentro do texto de um Block, usando o Normalizer (Fase 3) pra validar. Ver PHX-NEW no topo daquele arquivo pro contexto e princípios completos (achar padrão !…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_labeled_ean_with_valid_checksum` | Labeled ean with valid checksum |
| ☐ | `test_labeled_ean_with_invalid_checksum_is_preserved_not_discarded` | Achado real do usuário: "achar um padrão != aceitar como verdade" - um EAN rotulado com dígito verificador ERRADO ainda vira Candidate, só com valid=F… |
| ☐ | `test_labeled_ncm` | Labeled ncm |
| ☐ | `test_labeled_cest` | Labeled cest |
| ☐ | `test_labeled_price_with_currency` | Labeled price with currency |
| ☐ | `test_labeled_price_min_and_max_get_distinct_field_types` | PHX-FIX (achado real testando a Fase 6/Evidence contra documentos reais): "Preço Mínimo"/"Preço Máximo" precisam virar field_types DIFERENTES (price_m… |
| ☐ | `test_labeled_price_without_qualifier_stays_generic` | Labeled price without qualifier stays generic |
| ☐ | `test_labeled_weight_with_unit` | Labeled weight with unit |
| ☐ | `test_labeled_weight_in_grams_converts_to_canonical_kg_and_keeps_original` | PHX-FIX: achado real testando a Fase 6 - "Peso: 600g" precisa chegar ao Candidate já convertido pra kg (0.6), preservando g/600 como original_unit/par… |
| ☐ | `test_ncm_without_label_is_not_detected_as_ncm` | Ncm without label is not detected as ncm |
| ☐ | `test_unlabeled_email_is_found` | Unlabeled email is found |
| ☐ | `test_unlabeled_price_with_currency_symbol_is_found` | Unlabeled price with currency symbol is found |
| ☐ | `test_unlabeled_valid_ean_is_found_by_checksum_alone` | Unlabeled valid ean is found by checksum alone |
| ☐ | `test_unlabeled_invalid_length_number_is_not_treated_as_ean` | Um número de 13 dígitos com checksum ERRADO e SEM rótulo não deve virar Candidate de EAN - ruído demais sem nenhum sinal (nem rótulo, nem checksum vál… |
| ☐ | `test_unlabeled_formatted_phone_is_found` | Unlabeled formatted phone is found |
| ☐ | `test_unlabeled_date_numeric_format_is_found` | Unlabeled date numeric format is found |
| ☐ | `test_offsets_point_at_the_raw_value_inside_the_text` | Offsets point at the raw value inside the text |
| ☐ | `test_same_span_same_field_type_deduplicated_keeping_highest_confidence` | Same span same field type deduplicated keeping highest confidence |
| ☐ | `test_table_block_uses_column_header_as_implicit_label` | Table block uses column header as implicit label |
| ☐ | `test_table_block_without_useful_header_still_scans_cell_text` | Table block without useful header still scans cell text |
| ☐ | `test_unlabeled_ean_checksum_does_not_fire_inside_an_already_labeled_ncm` | Achado real: um NCM de 8 dígitos pode, por coincidência, "passar" no dígito verificador de EAN-8 - sem esta regra isso virava um segundo Candidate "ea… |
| ☐ | `test_unlabeled_phone_does_not_fire_inside_an_already_labeled_ean` | Achado real: um EAN de 13 dígitos contém, por acaso, uma sequência de 11 dígitos que bate no formato de telefone brasileiro - sem esta regra isso vira… |
| ☐ | `test_heading_block_is_scanned_like_paragraph` | Heading block is scanned like paragraph |
| ☐ | `test_image_block_produces_no_candidates` | Image block produces no candidates |
| ☐ | `test_empty_text_produces_no_candidates` | Empty text produces no candidates |
| ☐ | `test_height_width_depth_with_unit_in_label_convert_to_canonical_meters` | Achado real: "Altura (cm): 34,8" - a unidade fica só no RÓTULO, nunca no valor. Sem propagar essa dica pro Normalizer, isso nunca seria reconhecido co… |
| ☐ | `test_height_with_unit_in_label_equals_height_with_unit_in_value` | Height with unit in label equals height with unit in value |
| ☐ | `test_weight_bugfix_unit_hint_in_label_now_recognized` | PHX-FIX: antes desta expansão, "Peso (Kg): 24,500" não gerava Candidate NENHUM (o rótulo fechado da Fase 4 original não previa unidade colada no rótul… |
| ☐ | `test_brand_label_strips_html_noise_and_stops_at_pipe` | Achado real (linha "Ficha Técnica" das descrições HTML): "<b>Marca:</b> <b>Bonafont (Danone) |</b> <b>Volume:</b> ...". |
| ☐ | `test_tags_label_splits_and_cleans_semicolon_list` | Tags label splits and cleans semicolon list |
| ☐ | `test_description_html_block_detected_by_format_alone_no_label_needed` | Achado real: o delimitador textual "[DESCRIÇÃO DO PRODUTO ...]" quase sempre aparece em trecho INSTRUCIONAL da conversa, não colado no HTML de verdade… |
| ☐ | `test_description_html_rejects_multiline_but_preserves_raw` | Description html rejects multiline but preserves raw |
| ☐ | `test_explicit_product_name_recognizes_labeled_name_but_not_titulo` | PHX-NEW: "Título" foi deliberadamente excluído do vocabulário de `explicit_product_name` - achado real: nos documentos-fonte, "Título:" aparece muito … |
| ☐ | `test_included_items_and_specifications_labels` | Included items and specifications labels |
| ☐ | `test_table_header_maps_new_dimensional_and_text_fields` | Table header maps new dimensional and text fields |
| ☐ | `test_cost_price_labeled_variants_produce_commercial_money_shape` | Cost price labeled variants produce commercial money shape |
| ☐ | `test_retail_price_labeled_variants_produce_commercial_money_shape` | Retail price labeled variants produce commercial money shape |
| ☐ | `test_wholesale_price_labeled_variants` | Wholesale price labeled variants |
| ☐ | `test_wholesale_min_quantity_is_a_bare_quantity_never_currency` | Wholesale min quantity is a bare quantity never currency |
| ☐ | `test_compare_at_price_and_sale_price_require_the_word_preco` | Pedido explícito do usuário: "De:"/"Por:" isolados são palavras comuns demais pra virar rótulo de campo - só "Preço De:"/"Preço Por:" contam (mesma fi… |
| ☐ | `test_generic_price_family_unaffected_for_non_overlapping_labels` | "Preço:"/"Valor:"/"Preço Mínimo:"/"Preço Máximo:" soltos continuam 100% inalterados pela expansão comercial - só "Preço de Custo"/"Preço de Venda" mud… |
| ☐ | `test_preco_de_venda_and_preco_de_custo_no_longer_also_produce_generic_price` | PHX-NEW: achado arquitetural desta rodada - o `_PRICE_LABEL_RE` genérico já reconhecia "Preço de Venda"/"Preço de Custo" como rótulo, mapeando pra `pr… |
| ☐ | `test_table_header_maps_commercial_price_fields_before_generic_price` | As colunas reais do MarketUP ("Preço de Custo", "Preço Venda Varejo", "Preço Venda Atacado", "Preço De", "Preço Por") todas contêm a palavra "Preço" -… |


### test_document_normalizer.py
**Módulo:** `phoenix_kernel.documents.normalizer`

Testes da Fase 3 do "Document Pipeline V2" (phoenix_kernel/documents/ normalizer.py) - conversão de texto cru pra valor normalizado, Python puro, sem LLM/OCR/rede. Ver PHX-NEW no topo daquele arquivo pro contexto completo.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_currency_with_symbol_and_thousands_separator` | Currency with symbol and thousands separator |
| ☐ | `test_currency_without_symbol` | Currency without symbol |
| ☐ | `test_currency_invalid_text_stays_invalid_and_keeps_raw` | Currency invalid text stays invalid and keeps raw |
| ☐ | `test_number_with_unit_weight_kg` | Number with unit weight kg |
| ☐ | `test_number_with_unit_no_space` | Number with unit no space |
| ☐ | `test_number_without_unit` | Number without unit |
| ☐ | `test_number_negative_value` | PHX-FIX: "mm" NÃO é a unidade canônica de comprimento (é "m") - o valor negativo também passa pela conversão dimensional. |
| ☐ | `test_weight_grams_converts_to_canonical_kg` | Weight grams converts to canonical kg |
| ☐ | `test_weight_kg_and_grams_normalize_to_the_same_canonical_value` | 0,600 kg == 600 g - o pedido central deste fix. |
| ☐ | `test_one_kg_equals_a_thousand_grams` | One kg equals a thousand grams |
| ☐ | `test_volume_ml_and_liters_normalize_to_the_same_canonical_value` | Volume ml and liters normalize to the same canonical value |
| ☐ | `test_length_cm_converts_to_canonical_meters` | Length cm converts to canonical meters |
| ☐ | `test_same_number_different_unit_is_not_silently_equal` | 0,600 kg (=600g) é bem diferente de 600 kg - a conversão nunca "aproxima" nada, cada unidade converte pelo seu próprio fator. |
| ☐ | `test_ml_and_liters_with_same_number_are_not_equal` | 500 ml != 500 L - mesma grandeza numérica no texto, valores fisicamente bem diferentes depois de canonizar. |
| ☐ | `test_unrecognized_unit_passes_through_without_conversion` | Unrecognized unit passes through without conversion |
| ☐ | `test_date_br_format_four_digit_year` | Date br format four digit year |
| ☐ | `test_date_iso_format_passthrough` | Date iso format passthrough |
| ☐ | `test_date_br_format_two_digit_year_expands_to_2000s` | Date br format two digit year expands to 2000s |
| ☐ | `test_date_with_portuguese_month_name` | Date with portuguese month name |
| ☐ | `test_date_impossible_calendar_date_is_invalid` | Date impossible calendar date is invalid |
| ☐ | `test_date_garbage_text_is_invalid` | Date garbage text is invalid |
| ☐ | `test_ean13_valid_checksum_accepted` | Ean13 valid checksum accepted |
| ☐ | `test_ean13_wrong_checksum_rejected` | Ean13 wrong checksum rejected |
| ☐ | `test_ean_formatted_with_spaces_still_validates` | Ean formatted with spaces still validates |
| ☐ | `test_ean_wrong_length_rejected` | Ean wrong length rejected |
| ☐ | `test_ncm_with_dots_normalizes_to_plain_digits` | Ncm with dots normalizes to plain digits |
| ☐ | `test_ncm_wrong_digit_count_rejected` | Ncm wrong digit count rejected |
| ☐ | `test_cest_with_dots_normalizes_to_plain_digits` | Cest with dots normalizes to plain digits |
| ☐ | `test_cest_wrong_digit_count_rejected` | Cest wrong digit count rejected |
| ☐ | `test_phone_mobile_with_country_code_and_formatting` | Phone mobile with country code and formatting |
| ☐ | `test_phone_mobile_without_country_code` | Phone mobile without country code |
| ☐ | `test_phone_landline_ten_digits` | Phone landline ten digits |
| ☐ | `test_phone_wrong_digit_count_rejected` | Phone wrong digit count rejected |
| ☐ | `test_email_normalizes_to_lowercase` | Email normalizes to lowercase |
| ☐ | `test_email_missing_at_sign_is_invalid` | Email missing at sign is invalid |


### test_document_pipeline_v2_schema.py
**Módulo:** `phoenix_kernel.documents.normalized`

Testes do contrato de dados da Fase 1 do "Document Pipeline V2" (phoenix_kernel/documents/normalized.py) - ver PHX-NEW no topo daquele arquivo pro contexto completo (achado real: preenchimento de planilha perdendo dezenas de produtos de uma vez quando um chunk de caracteres falha…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_paragraph_block_roundtrip` | Paragraph block roundtrip |
| ☐ | `test_heading_block_has_level` | Heading block has level |
| ☐ | `test_table_block_keeps_headers_and_rows_structured_not_flattened` | Achado real que motivou este schema: `_extract_docx` hoje achata cada linha de tabela em "cel1 | cel2 | cel3" sem cabeçalho. O `Block` de tabela nunca… |
| ☐ | `test_image_block_records_placeholder_before_any_ocr_exists` | Image block records placeholder before any ocr exists |
| ☐ | `test_normalized_document_roundtrip_preserves_block_order` | Normalized document roundtrip preserves block order |
| ☐ | `test_compute_document_id_is_content_based_not_path_based` | Compute document id is content based not path based |
| ☐ | `test_candidate_keeps_raw_and_normalized_value_separate` | Candidate keeps raw and normalized value separate |
| ☐ | `test_record_defaults_to_unknown_kind` | Record defaults to unknown kind |
| ☐ | `test_job_plan_sources_reference_document_id_not_a_file_path` | Job plan sources reference document id not a file path |
| ☐ | `test_job_state_tracks_status_per_record_not_per_chunk` | Job state tracks status per record not per chunk |


### test_docx_structural_parser.py
**Módulo:** `phoenix_kernel.documents.docx_parser`

Testes da Fase 2 do "Document Pipeline V2" (phoenix_kernel/documents/docx_parser.py) - parser estrutural real de DOCX, que produz um NormalizedDocument (Fase 1) na ORDEM REAL do documento. O teste mais importante deste arquivo é `test_paragraph_table_paragraph_order_is_preserved`…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_paragraph_table_paragraph_order_is_preserved` | O teste central desta investigação inteira: um parágrafo antes de uma tabela e outro depois dela devem permanecer NESSA ordem - não "todos os parágraf… |
| ☐ | `test_block_order_is_strictly_monotonic` | Block order is strictly monotonic |
| ☐ | `test_heading_level_is_captured` | Heading level is captured |
| ☐ | `test_paragraph_keeps_source_paragraph_index` | Paragraph keeps source paragraph index |
| ☐ | `test_empty_paragraph_does_not_become_a_block` | Empty paragraph does not become a block |
| ☐ | `test_table_headers_and_rows_are_structured_never_flattened` | Table headers and rows are structured never flattened |
| ☐ | `test_two_tables_keep_relative_order_with_surrounding_paragraphs` | Two tables keep relative order with surrounding paragraphs |
| ☐ | `test_embedded_image_becomes_placeholder_block` | Embedded image becomes placeholder block |
| ☐ | `test_document_id_is_based_on_file_content_not_path` | Document id is based on file content not path |
| ☐ | `test_roundtrip_through_json_preserves_order_and_structure` | Roundtrip through json preserves order and structure |


### test_evidence_engine.py
**Módulo:** `phoenix_kernel.documents.evidence_engine`

Testes da Fase 6 do "Document Pipeline V2" (phoenix_kernel/documents/ evidence_engine.py) - agrega Candidate(s) referenciados por um Record numa FieldEvidence por campo, com um vocabulário fechado de status (confirmed/ probable/ambiguous/conflict/invalid). Ver PHX-NEW no topo daq…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_two_independent_sources_agreeing_is_confirmed` | Two independent sources agreeing is confirmed |
| ☐ | `test_duplicate_same_text_elsewhere_does_not_inflate_to_confirmed` | Achado real (Fase 2/5): a conversa repete/revisa as mesmas seções em outro lugar do documento - o MESMO parágrafo aparecendo duas vezes não pode virar… |
| ☐ | `test_single_source_high_confidence_is_probable` | Single source high confidence is probable |
| ☐ | `test_single_source_low_confidence_is_ambiguous` | Cenário sintético - os detectores atuais da Fase 4 nunca produzem confidence < 0.7 num candidato válido (ver limitação documentada no módulo), então e… |
| ☐ | `test_weight_in_kg_and_grams_for_same_product_is_confirmed_not_conflict` | PHX-FIX (achado real testando esta própria fase contra os documentos reais): "Peso: 0,600 kg" e "Peso: 600g" no MESMO record viravam "conflict" antes … |
| ☐ | `test_two_different_valid_values_is_conflict` | Two different valid values is conflict |
| ☐ | `test_conflict_evidence_count_deduplicates_repeated_source_per_value` | Conflict evidence count deduplicates repeated source per value |
| ☐ | `test_only_invalid_candidates_yields_invalid_status_and_preserves_evidence` | Only invalid candidates yields invalid status and preserves evidence |
| ☐ | `test_evidence_entries_carry_full_traceability_fields` | Evidence entries carry full traceability fields |
| ☐ | `test_table_block_source_is_table_paragraph_source_is_text` | Table block source is table paragraph source is text |
| ☐ | `test_multiple_field_types_in_same_record_each_get_their_own_field_evidence` | Multiple field types in same record each get their own field evidence |
| ☐ | `test_build_evidence_for_document_maps_by_record_id` | Build evidence for document maps by record id |
| ☐ | `test_record_with_no_matching_candidates_yields_no_field_evidence` | Record with no matching candidates yields no field evidence |
| ☐ | `test_field_evidence_roundtrip_through_dict` | Field evidence roundtrip through dict |


### test_identity_engine.py
**Módulo:** `phoenix_kernel.documents.evidence_engine`

Testes da Fase 9 do "Document Pipeline V2" (phoenix_kernel/documents/identity_engine.py) - Identity/Merge/Dedup: quais Records representam a MESMA entidade real, sem nunca apagar/alterar um Record original. Ver PHX-NEW no topo daquele arquivo pro contexto e princípios completos (…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_same_valid_ean_is_auto_merge` | Same valid ean is auto merge |
| ☐ | `test_different_valid_ean_never_auto_merges` | Different valid ean never auto merges |
| ☐ | `test_same_name_and_ncm_but_different_ean_stays_separated` | NCM igual e nome idêntico NÃO revertem o bloqueio de EAN diferente - identidade nunca é decidida por NCM (pedido explícito: "NCM identifica classe fis… |
| ☐ | `test_same_product_written_differently_is_flagged_as_duplicate_candidate_not_silently_merged` | "Coca Cola 350ml" vs "Coca-Cola Lata 350 ml" - sem EAN nenhum dos dois lados. Similaridade de nome + quantidade equivalente têm que sinalizar um candi… |
| ☐ | `test_same_brand_different_variant_stays_separated` | "Pringles Original 165g" vs "Pringles Paprika 165g" - altíssima similaridade textual, mas são produtos DIFERENTES (variante diferente) - o peso de sim… |
| ☐ | `test_single_unit_vs_closed_box_of_twelve_stays_separated` | Single unit vs closed box of twelve stays separated |
| ☐ | `test_weight_equivalence_reuses_dimensional_canonicalization` | Weight equivalence reuses dimensional canonicalization |
| ☐ | `test_same_evidence_repeated_across_five_records_does_not_inflate_after_merge` | Same evidence repeated across five records does not inflate after merge |
| ☐ | `test_two_identical_records_with_different_price_yields_single_canonical_with_price_conflict` | Two identical records with different price yields single canonical with price conflict |
| ☐ | `test_invalid_and_valid_ean_across_records_both_preserved_valid_wins_status` | Invalid and valid ean across records both preserved valid wins status |
| ☐ | `test_transitive_matches_form_a_single_cluster` | Transitive matches form a single cluster |
| ☐ | `test_records_without_any_strong_signal_stay_unique` | Records without any strong signal stay unique |
| ☐ | `test_three_unique_records_produce_three_canonical_records` | Three unique records produce three canonical records |
| ☐ | `test_two_unique_plus_one_cluster_of_two_produces_three_canonical_records` | Two unique plus one cluster of two produces three canonical records |
| ☐ | `test_singleton_canonical_record_preserves_evidence_like_a_normal_merge` | Singleton canonical record preserves evidence like a normal merge |
| ☐ | `test_merge_never_modifies_original_records_and_preserves_order` | Merge never modifies original records and preserves order |
| ☐ | `test_find_candidate_pairs_only_compares_records_sharing_a_bucket` | Find candidate pairs only compares records sharing a bucket |
| ☐ | `test_field_evidence_after_merge_matches_direct_evidence_engine_call` | A Fase 9 não reimplementa nada da Fase 6 - o resultado de `build_canonical_record` pra um único record "cluster" de 1 elemento (via chamada direta, ig… |


### test_job_executor.py
**Módulo:** `phoenix_kernel.documents.job_executor`

Testes da Fase 7 do "Document Pipeline V2" (phoenix_kernel/documents/ job_executor.py) - Job Planner/Executor: cria `Task`s determinísticas por `Record` (Fase 5) a partir de um `JobPlan` (Fase 1), executa com controle de status/retry, e resolve checkpoint/resume via `input_hash`.…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_two_hundred_records_produce_two_hundred_distinct_tasks` | Two hundred records produce two hundred distinct tasks |
| ☐ | `test_task_id_is_stable_for_same_record_and_operation` | Rodar o planejamento do MESMO job duas vezes tem que produzir os MESMOS task_ids - é isso que torna checkpoint/resume possível. |
| ☐ | `test_task_is_never_a_chunk_style_id` | "Task não é Chunk" - regra explícita do usuário: a identidade é record_id + operation, nunca um número sequencial de chunk. |
| ☐ | `test_new_task_starts_pending_with_zero_attempts` | New task starts pending with zero attempts |
| ☐ | `test_task_failure_does_not_stop_or_corrupt_other_tasks` | Cenário exigido: falha na task 117 -> 116 continuam DONE -> 117 FAILED -> 118+ não perdem estado (continuam sendo tentadas/DONE). |
| ☐ | `test_llm_unavailable_does_not_block_pure_python_tasks` | Cenário exigido explicitamente: uma tarefa que dependeria de LLM (indisponível, simulado por uma exceção) não pode impedir tarefas puramente Python de… |
| ☐ | `test_retry_gives_up_after_max_attempts` | Retry gives up after max attempts |
| ☐ | `test_dependencies_block_task_until_satisfied` | Dependencies block task until satisfied |
| ☐ | `test_run_pending_tasks_resolves_dependency_within_the_same_pass_when_ordered_first` | `run_pending_tasks` processa a lista em UMA passada, na ordem dada, atualizando o status conforme vai - então uma dependência que vem ANTES na lista j… |
| ☐ | `test_run_pending_tasks_leaves_task_pending_when_dependency_comes_later_in_the_list` | O inverso do teste acima: `run_pending_tasks` NÃO faz múltiplas passadas nem reordena - se a dependência aparece DEPOIS na lista (ou numa chamada futu… |
| ☐ | `test_unchanged_input_reuses_previous_result_without_rerunning` | Unchanged input reuses previous result without rerunning |
| ☐ | `test_changed_input_forces_task_to_rerun` | Changed input forces task to rerun |
| ☐ | `test_resume_after_restart_does_not_redo_already_done_tasks` | Cenário exigido: reinicia o Phoenix -> retoma da task que falhou -> não refaz as que já estavam DONE. |
| ☐ | `test_apply_tasks_to_job_state_and_json_roundtrip_preserves_tasks` | Apply tasks to job state and json roundtrip preserves tasks |
| ☐ | `test_compute_input_hash_incorporates_evidence_status_when_given` | Compute input hash incorporates evidence status when given |
| ☐ | `test_compute_input_hash_is_stable_for_identical_input` | Compute input hash is stable for identical input |


### test_pipeline_orchestrator.py
**Módulo:** `phoenix_kernel.documents.pipeline_orchestrator`

Testes do orquestrador do Document Pipeline V2 (o fio que liga as peças).


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_columns_resolved_automatically_from_headers` | Columns resolved automatically from headers |
| ☐ | `test_pipeline_writes_deterministically_with_audit` | Pipeline writes deterministically with audit |
| ☐ | `test_pipeline_is_deterministic` | Mesma entrada -> mesma saída (é a garantia do caminho sem LLM). |
| ☐ | `test_template_never_overwritten` | Template never overwritten |


### test_record_segmenter.py
**Módulo:** `phoenix_kernel.documents.candidate_engine`

Testes da Fase 5 do "Document Pipeline V2" (phoenix_kernel/documents/ record_segmenter.py) - agrupa Block+Candidate em Record. Ver PHX-NEW no topo daquele arquivo pro contexto e princípios completos (só agrupa, nunca valida/classifica/chama LLM). O teste mais importante deste arq…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_two_distinct_products_become_two_separate_records` | Two distinct products become two separate records |
| ☐ | `test_consecutive_data_blocks_without_title_still_split` | Padrão real visto no documento do usuário: blocos de dados ERP em sequência, sem nenhuma linha de título separando um do outro - ainda assim precisam … |
| ☐ | `test_invalid_ean_is_preserved_inside_record_not_dropped_or_fixed` | Regra explícita do usuário: o Segmenter não corrige nem descarta Candidate - um EAN inválido continua fazendo parte do record. |
| ☐ | `test_record_start_and_end_order_span_its_blocks` | Record start and end order span its blocks |
| ☐ | `test_image_block_is_absorbed_without_starting_a_new_record` | Image block is absorbed without starting a new record |
| ☐ | `test_table_with_strong_identifier_can_start_new_record` | Table with strong identifier can start new record |
| ☐ | `test_confidence_is_higher_with_more_valid_strong_identifiers` | Confidence is higher with more valid strong identifiers |
| ☐ | `test_no_strong_identifier_anywhere_yields_low_confidence_single_record` | No strong identifier anywhere yields low confidence single record |
| ☐ | `test_long_stretch_without_any_signal_forces_a_new_record_boundary` | Achado real testando com o segundo documento real do usuário ("instruções para construção de site de vendas.docx"): mesmo depois do fix do título-semp… |
| ☐ | `test_empty_document_yields_no_records` | Empty document yields no records |
| ☐ | `test_records_do_not_reorder_blocks` | Records do not reorder blocks |


### test_semantic_resolver.py
**Módulo:** `phoenix_kernel.documents.evidence_engine`

Testes da Fase 8 do "Document Pipeline V2" (phoenix_kernel/documents/semantic_resolver.py) - Semantic Resolver: o LLM entra como fonte de EVIDÊNCIA, nunca como autoridade. Ver PHX-NEW no topo daquele arquivo pro contexto e princípios completos: gating por status da Fase 6, valida…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_confirmed_never_needs_semantic_resolution` | Confirmed never needs semantic resolution |
| ☐ | `test_probable_below_high_confidence_threshold_needs_resolution` | Probable below high confidence threshold needs resolution |
| ☐ | `test_probable_above_high_confidence_threshold_does_not_need_resolution` | Probable above high confidence threshold does not need resolution |
| ☐ | `test_weak_statuses_with_evidence_need_resolution` | Weak statuses with evidence need resolution |
| ☐ | `test_weak_statuses_without_any_evidence_do_not_need_resolution` | Sem nenhum trecho de evidência pra mostrar, a microtarefa não tem contexto nenhum a oferecer - chamar o LLM seria inútil. |
| ☐ | `test_build_semantic_task_has_stable_semantic_task_id` | Build semantic task has stable semantic task id |
| ☐ | `test_build_semantic_task_snippets_come_only_from_field_evidence_not_raw_document` | Build semantic task snippets come only from field evidence not raw document |
| ☐ | `test_build_semantic_task_caps_number_of_snippets` | Build semantic task caps number of snippets |
| ☐ | `test_valid_response_is_accepted` | Valid response is accepted |
| ☐ | `test_valid_response_as_already_parsed_dict_is_accepted` | Valid response as already parsed dict is accepted |
| ☐ | `test_invalid_json_is_rejected` | Invalid json is rejected |
| ☐ | `test_non_dict_json_is_rejected` | Non dict json is rejected |
| ☐ | `test_missing_required_key_is_rejected` | Missing required key is rejected |
| ☐ | `test_confidence_out_of_range_is_rejected` | Confidence out of range is rejected |
| ☐ | `test_confidence_wrong_type_is_rejected` | Confidence wrong type is rejected |
| ☐ | `test_confidence_as_bool_is_rejected` | bool é subclasse de int em Python - precisa ser explicitamente barrado, senão `True`/`False` passariam como 1.0/0.0 silenciosamente. |
| ☐ | `test_reason_wrong_type_is_rejected` | Reason wrong type is rejected |
| ☐ | `test_selected_value_outside_allowed_values_is_rejected_even_if_plausible` | O documento (ou uma instrução escondida nele) poderia tentar fazer o LLM "inventar" uma categoria nova, plausível mas fora da allowlist - isto tem que… |
| ☐ | `test_extra_injected_keys_are_rejected_even_with_an_otherwise_valid_answer` | Uma resposta tentando adicionar uma chave extra (ex: pra tentar influenciar o executor a mudar status/comportamento) é rejeitada POR INTEIRO - o valor… |
| ☐ | `test_resolution_to_candidate_carries_full_provenance` | Resolution to candidate carries full provenance |
| ☐ | `test_resolution_to_candidate_input_hash_is_stable_for_the_same_task` | Resolution to candidate input hash is stable for the same task |
| ☐ | `test_resolve_if_needed_returns_none_and_never_calls_llm_when_confirmed` | Resolve if needed returns none and never calls llm when confirmed |
| ☐ | `test_resolve_if_needed_returns_candidate_for_accepted_response` | Resolve if needed returns candidate for accepted response |
| ☐ | `test_resolve_if_needed_returns_none_when_response_is_rejected` | Uma resposta rejeitada (fora do schema/allowlist) nunca vira Candidate - o campo simplesmente segue sem essa evidência extra, nunca quebra a execução. |
| ☐ | `test_accepted_llm_evidence_elevates_ambiguous_to_confirmed_via_evidence_engine` | Um campo "ambiguous" (1 única fonte fraca) recebe uma segunda evidência - desta vez do LLM, concordando com o valor - e o MESMO `build_field_evidence`… |
| ☐ | `test_llm_evidence_disagreeing_keeps_conflict_never_overrules_python` | O LLM "confiante" discordando de um valor já existente NÃO decide o campo sozinho - continua "conflict", com a nova evidência apenas registrada na lis… |
| ☐ | `test_semantic_resolution_runs_through_job_executor_task_machinery` | Uma resolução semântica rodando como o `run_fn` de uma `Task` da Fase 7 - uma chamada de LLM "indisponível" (aqui simulada por uma resposta rejeitada)… |
| ☐ | `test_semantic_task_failure_does_not_block_other_tasks_in_run_pending_tasks` | Semantic task failure does not block other tasks in run pending tasks |


### test_taxonomy_resolver.py
**Módulo:** `phoenix_kernel.documents.evidence_engine`

Testes do grupo semântico da expansão de vocabulário V2 (phoenix_kernel/documents/taxonomy_resolver.py) - category/subcategory/ store_category/store_subcategory via Fase 8 (Semantic Resolver), reaproveitada sem modificação nenhuma. Ver PHX-NEW no topo daquele arquivo pro contexto…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_taxonomy_source_prefers_erp_template_over_everything` | Taxonomy source prefers erp template over everything |
| ☐ | `test_taxonomy_source_prefers_job_plan_over_external_and_inferred` | Taxonomy source prefers job plan over external and inferred |
| ☐ | `test_taxonomy_source_prefers_external_catalog_over_inferred` | Taxonomy source prefers external catalog over inferred |
| ☐ | `test_taxonomy_source_inferred_from_documents_is_always_provisional` | Achado real que motivou esta rodada: texto dos dois documentos tem linguagem de estratégia/marketing que pode não ser categoria oficial nenhuma - por … |
| ☐ | `test_taxonomy_source_with_nothing_passed_is_none_origin_and_empty` | Taxonomy source with nothing passed is none origin and empty |
| ☐ | `test_taxonomy_source_never_infers_from_documents_automatically` | Nenhuma chamada sem `inferred_from_documents` explícito produz origin="provisional" - o módulo nunca preenche isso sozinho. |
| ☐ | `test_root_level_allowed_values_ignores_parent_value_argument` | Root level allowed values ignores parent value argument |
| ☐ | `test_child_level_without_parent_value_has_no_allowed_values` | Child level without parent value has no allowed values |
| ☐ | `test_child_level_allowed_values_reduced_by_chosen_parent_value` | Child level allowed values reduced by chosen parent value |
| ☐ | `test_child_level_unknown_parent_value_has_no_allowed_values` | Child level unknown parent value has no allowed values |
| ☐ | `test_context_snippets_uses_default_fields_and_skips_missing` | Context snippets uses default fields and skips missing |
| ☐ | `test_context_snippets_skips_empty_value_field` | Context snippets skips empty value field |
| ☐ | `test_context_snippets_respects_max_snippets` | Context snippets respects max snippets |
| ☐ | `test_context_snippets_empty_when_no_context_field_resolved` | Context snippets empty when no context field resolved |
| ☐ | `test_needs_resolution_true_when_no_existing_evidence_at_all` | Caso comum hoje: nenhum documento rotula categoria explicitamente, então não existe FieldEvidence nenhum pra 'category' - resolução por contexto é o ú… |
| ☐ | `test_needs_resolution_false_when_existing_evidence_already_confirmed` | Needs resolution false when existing evidence already confirmed |
| ☐ | `test_needs_resolution_true_when_existing_evidence_is_weak_probable` | Needs resolution true when existing evidence is weak probable |
| ☐ | `test_happy_path_resolves_category_then_reduces_subcategory_allowlist` | Happy path resolves category then reduces subcategory allowlist |
| ☐ | `test_no_context_available_skips_both_levels_without_calling_llm` | No context available skips both levels without calling llm |
| ☐ | `test_no_allowlist_available_skips_without_calling_llm` | No allowlist available skips without calling llm |
| ☐ | `test_existing_confirmed_category_skips_llm_but_still_resolves_subcategory` | Guarda pedida explicitamente pelo usuário: se já existe leitura determinística boa o bastante pra 'category' (ex: um rótulo explícito futuro), NÃO cha… |
| ☐ | `test_rejected_parent_response_never_attempts_child` | Resposta fora da allowlist é rejeitada pela MESMA validação estrita da Fase 8 (defesa contra prompt injection) - sem um valor de categoria válido, não… |
| ☐ | `test_child_without_known_values_for_chosen_parent_is_skipped_but_parent_still_resolved` | "Higiene"/"Limpeza" não têm subcategoria na fixture (achado real esperado: nem toda categoria tem uma lista de subcategorias fechada ainda) - a catego… |
| ☐ | `test_rejected_child_response_outside_reduced_allowlist_is_rejected` | A validação estrita da Fase 8 vale IGUAL pra allowlist reduzida do filho - um valor de fora do subconjunto de "Bebidas" (ex: "Massas", que só existe e… |
| ☐ | `test_store_category_pair_is_independent_from_category_pair` | Pedido explícito do usuário: category/subcategory (ERP) e store_category/store_subcategory (loja virtual) são DOIS PARES INDEPENDENTES - mesmo usando … |
| ☐ | `test_build_taxonomy_task_has_stable_semantic_task_id` | Build taxonomy task has stable semantic task id |


## 📊 Planilhas & Preenchimento

*76 testes em 8 arquivo(s).*


### test_batch_fill.py
**Módulo:** `phoenix_kernel.documents.batch_fill`

Testes do preenchimento de planilha em lotes com checkpoint incremental.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_rank_prefers_nvme_then_ssd_then_hdd` | Rank prefers nvme then ssd then hdd |
| ☐ | `test_disk_without_space_never_wins` | Disk without space never wins |
| ☐ | `test_batch_size_scales_with_model_and_vram` | Batch size scales with model and vram |
| ☐ | `test_split_has_no_chunk_ceiling` | Split has no chunk ceiling |
| ☐ | `test_checkpoint_written_every_batch_and_final_matches` | Checkpoint written every batch and final matches |
| ☐ | `test_failed_batch_is_skipped_not_fatal` | Failed batch is skipped not fatal |


### test_fill_spreadsheet_template_bridge.py
**Módulo:** `phoenix_kernel.resident.resident_manager`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_fills_template_from_source_document` | Fills template from source document |
| ☐ | `test_template_must_be_xlsx` | Template must be xlsx |
| ☐ | `test_missing_source_file_fails_without_calling_runtime` | Missing source file fails without calling runtime |
| ☐ | `test_missing_template_file_fails_without_calling_runtime` | Missing template file fails without calling runtime |
| ☐ | `test_invalid_json_after_retries_fails_cleanly` | Invalid json after retries fails cleanly |
| ☐ | `test_mismatched_sheet_name_falls_back_to_first_sheet` | Mismatched sheet name falls back to first sheet |
| ☐ | `test_runtime_failure_propagates_real_error` | Runtime failure propagates real error |
| ☐ | `test_empty_rows_from_model_fails_cleanly` | Empty rows from model fails cleanly |


### test_fill_spreadsheet_template_chunking.py
**Módulo:** `phoenix_kernel.resident.resident_manager`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_split_empty_text_returns_no_chunks` | Split empty text returns no chunks |
| ☐ | `test_split_text_smaller_than_budget_is_a_single_chunk` | Split text smaller than budget is a single chunk |
| ☐ | `test_split_keeps_small_paragraphs_together_in_one_chunk` | Split keeps small paragraphs together in one chunk |
| ☐ | `test_split_never_cuts_a_paragraph_in_half` | Split never cuts a paragraph in half |
| ☐ | `test_split_hard_slices_a_single_paragraph_bigger_than_the_budget` | Split hard slices a single paragraph bigger than the budget |
| ☐ | `test_split_falls_back_to_single_newline_when_no_blank_lines` | Split falls back to single newline when no blank lines |
| ☐ | `test_row_identity_prefers_barcode_like_value` | Row identity prefers barcode like value |
| ☐ | `test_row_identity_falls_back_to_name_like_column` | Row identity falls back to name like column |
| ☐ | `test_row_identity_is_unique_without_barcode_or_name_column` | Row identity is unique without barcode or name column |
| ☐ | `test_merge_keeps_distinct_products_from_different_chunks` | Merge keeps distinct products from different chunks |
| ☐ | `test_merge_dedupes_same_product_keeping_the_later_chunk_version` | Merge dedupes same product keeping the later chunk version |
| ☐ | `test_merge_dedupes_by_barcode_across_chunks_even_with_different_names` | Merge dedupes by barcode across chunks even with different names |
| ☐ | `test_large_document_is_split_and_all_chunks_are_queried` | Large document is split and all chunks are queried |
| ☐ | `test_large_document_dedupes_product_revised_in_a_later_chunk` | Large document dedupes product revised in a later chunk |
| ☐ | `test_one_failed_chunk_does_not_abort_the_whole_document` | One failed chunk does not abort the whole document |
| ☐ | `test_max_chunks_safety_cap_is_reported_not_silently_dropped` | Max chunks safety cap is reported not silently dropped |
| ☐ | `test_small_document_still_uses_exactly_one_chunk_and_two_calls_on_bad_json` | Small document still uses exactly one chunk and two calls on bad json |
| ☐ | `test_default_small_model_keeps_the_original_medium_timeout_budget` | Default small model keeps the original medium timeout budget |
| ☐ | `test_large_model_gets_the_larger_timeout_budget_per_chunk` | Large model gets the larger timeout budget per chunk |


### test_fill_xlsx_template_engine.py
**Módulo:** `phoenix_kernel.documents.engine`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_read_structure_finds_header_and_last_row` | Read structure finds header and last row |
| ☐ | `test_read_structure_empty_sheet_reports_no_headers` | Read structure empty sheet reports no headers |
| ☐ | `test_read_structure_multiple_sheets` | Read structure multiple sheets |
| ☐ | `test_fill_appends_rows_after_existing_data` | Fill appends rows after existing data |
| ☐ | `test_fill_preserves_untouched_sheet_and_formula` | A promessa central do recurso: outra planilha e uma fórmula não tocadas continuam intactas depois do preenchimento - ao contrário de rebuild_document(… |
| ☐ | `test_fill_matches_headers_case_insensitively` | Fill matches headers case insensitively |
| ☐ | `test_fill_auto_creates_column_for_unmatched_key` | Fill auto creates column for unmatched key |
| ☐ | `test_fill_creates_header_from_scratch_on_blank_template` | Fill creates header from scratch on blank template |
| ☐ | `test_fill_single_sheet_template_ignores_mismatched_sheet_name` | LLM pode não reproduzir o nome exato da planilha - com só UMA planilha no template, usa ela mesmo assim em vez de falhar. |
| ☐ | `test_fill_multi_sheet_template_reports_unmatched_sheet_name` | Fill multi sheet template reports unmatched sheet name |
| ☐ | `test_fill_never_overwrites_the_template_file` | Fill never overwrites the template file |
| ☐ | `test_fill_rejects_non_xlsx_template` | Fill rejects non xlsx template |


### test_output_writer.py
**Módulo:** `phoenix_kernel.documents.evidence_engine`

Fase 10 - XLSX Output Writer: testes. Cobre exatamente os cenários pedidos pelo usuário na especificação de Fase 10, com foco especial em PRESERVAÇÃO DE TEMPLATE REAL - "Isso vale mais para a Phoenix do que provar apenas que openpyxl.Workbook() consegue criar um .xlsx." O arquivo…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_confirmed_and_probable_fields_write_value` | Confirmed and probable fields write value |
| ☐ | `test_conflict_field_leaves_cell_blank_and_writes_audit` | Conflict field leaves cell blank and writes audit |
| ☐ | `test_invalid_field_leaves_cell_blank_and_writes_audit` | Invalid field leaves cell blank and writes audit |
| ☐ | `test_missing_required_field_leaves_blank_and_audits_without_aborting` | Missing required field leaves blank and audits without aborting |
| ☐ | `test_missing_optional_field_is_blank_without_audit` | Missing optional field is blank without audit |
| ☐ | `test_multiple_records_write_sequential_rows` | Multiple records write sequential rows |
| ☐ | `test_refuses_to_overwrite_template_path` | Refuses to overwrite template path |
| ☐ | `test_unknown_header_raises_explicit_error` | Unknown header raises explicit error |
| ☐ | `test_unsupported_conflict_policy_raises_not_implemented` | Unsupported conflict policy raises not implemented |
| ☐ | `test_template_preservation_end_to_end` | O teste mais importante desta fase, pedido explicitamente pelo usuário: depois do Writer rodar, o TEMPLATE ORIGINAL continua intacto byte a byte, e o … |
| ☐ | `test_write_blank_workbook_fallback` | Write blank workbook fallback |


### test_pipeline_fill_route.py
**Módulo:** `phoenix_kernel.documents.pipeline_orchestrator`

Testes do preenchimento DETERMINÍSTICO (rota /pipeline-fill). Regressão do bug real: preencher planilha via LLM (/fill-template) passou de 90min num catálogo real e virou processo órfão. O caminho determinístico faz o mesmo em segundos, sem LLM — logo não há inferência para trava…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_deterministic_fill_uses_no_llm_and_is_fast` | O caminho determinístico não chama nenhum modelo — é só parser + regras. Prova que preenche a partir do texto sem inferência. |
| ☐ | `test_deterministic_fill_then_smart_fill_completes_empty_cells` | Deterministic fill then smart fill completes empty cells |


### test_smart_filler.py
**Módulo:** `phoenix_kernel.documents.smart_filler`

Testes do Smart Filler — a Phoenix raciocinando e preenchendo.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_derives_by_rule_copy_default_and_sequential` | Derives by rule copy default and sequential |
| ☐ | `test_never_overwrites_existing_values` | Never overwrites existing values |
| ☐ | `test_fiscal_fields_are_never_guessed` | Fiscal fields are never guessed |
| ☐ | `test_placeholder_products_are_not_invented` | Placeholder products are not invented |
| ☐ | `test_generates_content_from_category_and_name` | Generates content from category and name |
| ☐ | `test_llm_rewrite_is_optional_fallback` | Llm rewrite is optional fallback |
| ☐ | `test_llm_failure_falls_back_to_deterministic` | Llm failure falls back to deterministic |


### test_xlsx_structural_summary.py
**Módulo:** `phoenix_kernel.documents.engine`

Testes de regressão pra auditoria 2026-08-20, Seção 13 do LEIA-ME ("timeout XLSX"): o Document Engine estava despejando TODAS as linhas de um XLSX (via _extract_xlsx()) antes de truncar em [:12000] caracteres pra montar o prompt do LLM. Pra planilha grande isso era lento (constró…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_summarize_small_xlsx_reports_header_types_and_sample` | Summarize small xlsx reports header types and sample |
| ☐ | `test_summarize_xlsx_respects_sample_row_cap` | Summarize xlsx respects sample row cap |
| ☐ | `test_summarize_xlsx_handles_empty_sheet` | Summarize xlsx handles empty sheet |
| ☐ | `test_summarize_xlsx_caps_number_of_sheets_shown` | Summarize xlsx caps number of sheets shown |
| ☐ | `test_summarize_xlsx_stays_compact_for_large_sheet` | Summarize xlsx stays compact for large sheet |
| ☐ | `test_summarize_xlsx_missing_file_raises_document_engine_error` | Summarize xlsx missing file raises document engine error |
| ☐ | `test_read_document_direct_routes_xlsx_through_structural_summary` | Read document direct routes xlsx through structural summary |
| ☐ | `test_read_document_direct_non_xlsx_still_uses_extract_text_with_cap` | Read document direct non xlsx still uses extract text with cap |
| ☐ | `test_read_document_direct_returns_controlled_error_on_timeout` | Read document direct returns controlled error on timeout |
| ☐ | `test_edit_document_direct_returns_controlled_error_on_timeout` | Edit document direct returns controlled error on timeout |
| ☐ | `test_document_execute_timeout_is_well_under_node_abort` | Document execute timeout is well under node abort |


## 🏷️ Fiscal & Código de Barras

*10 testes em 2 arquivo(s).*


### test_barcode_finder.py
**Módulo:** `phoenix_kernel.documents.barcode_finder`

Testes do buscador de EAN — pesquisa, valida, e exige auditoria humana.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_ean13_checksum` | Ean13 checksum |
| ☐ | `test_search_extracts_and_validates_candidates` | Search extracts and validates candidates |
| ☐ | `test_nothing_applied_without_human_approval` | Nothing applied without human approval |
| ☐ | `test_approval_rejects_invalid_ean` | Approval rejects invalid ean |
| ☐ | `test_skips_products_that_already_have_ean` | Skips products that already have ean |


### test_fiscal_rag.py
**Módulo:** `phoenix_kernel.documents.fiscal_rag`

Testes do RAG fiscal — sugere NCM/CEST de dados auditados, nunca inventa.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_recovers_ncm_from_similar_audited_product` | Recovers ncm from similar audited product |
| ☐ | `test_consensus_boosts_confidence` | Consensus boosts confidence |
| ☐ | `test_unknown_product_returns_nothing` | Unknown product returns nothing |
| ☐ | `test_malformed_fiscal_code_never_enters_base` | Malformed fiscal code never enters base |
| ☐ | `test_suggest_for_row_only_fills_empty` | Suggest for row only fills empty |


## 📚 RAG (base de conhecimento)

*41 testes em 4 arquivo(s).*


### test_document_engine_bridge.py
**Módulo:** `phoenix_kernel.documents.engine`

Testes de regressão pra auditoria 2026-08-20 (achados #2, #3 e #10 do LEIA-ME): antes desta bateria, a Document Engine tinha DOIS problemas que nenhum teste cobria: 1. /api/documents/read e /api/documents/edit resolviam o modelo via resident.registry.resolve(), mas executavam com…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_docx_extract_and_rebuild_roundtrip` | Docx extract and rebuild roundtrip |
| ☐ | `test_xlsx_extract_and_rebuild_roundtrip` | Xlsx extract and rebuild roundtrip |
| ☐ | `test_pptx_extract_and_rebuild_roundtrip` | Pptx extract and rebuild roundtrip |
| ☐ | `test_read_document_direct_uses_resolved_model_and_tracks_it` | Read document direct uses resolved model and tracks it |
| ☐ | `test_read_document_direct_missing_file_fails_without_calling_runtime` | Read document direct missing file fails without calling runtime |
| ☐ | `test_edit_document_direct_rebuilds_file_on_disk` | Edit document direct rebuilds file on disk |
| ☐ | `test_edit_document_direct_requires_instruction` | Edit document direct requires instruction |
| ☐ | `test_ingest_route_is_a_real_alias_of_read_route` | Ingest route is a real alias of read route |
| ☐ | `test_read_route_calls_resident_not_runtime_execute_directly` | Read route calls resident not runtime execute directly |
| ☐ | `test_read_route_surfaces_resident_error_as_422` | Read route surfaces resident error as 422 |
| ☐ | `test_edit_route_returns_base64_and_cleans_temp_output` | Edit route returns base64 and cleans temp output |


### test_rag_blocked_for_cloud_providers.py
**Módulo:** *(vários módulos)*

Teste de regressão pra auditoria completa 2026-08-28, achado de privacidade real levantado pelo próprio usuário durante a revisão desta rodada: até aqui, `sendToProvider()` em AviaryApp.tsx consultava o RAG e anexava o contexto (trechos dos documentos indexados pelo usuário) ao s…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_chat_parameters_declares_the_block_flag` | Chat parameters declares the block flag |
| ☐ | `test_default_parameters_default_to_safe_blocked_state` | Default parameters default to safe blocked state |
| ☐ | `test_parameters_drawer_reset_also_defaults_to_blocked` | Parameters drawer reset also defaults to blocked |
| ☐ | `test_parameters_drawer_exposes_a_working_toggle` | Parameters drawer exposes a working toggle |
| ☐ | `test_send_to_provider_skips_the_rag_network_call_for_blocked_cloud_providers` | O núcleo da trava: quando isCloudProvider && blockRagOnCloudProviders, o fetch('/api/rag/query') não pode nem ser tentado - a proteção real é não faze… |
| ☐ | `test_local_providers_are_never_affected_by_the_cloud_privacy_flag` | Confirma que a trava é específica de nuvem - Ollama/llama-server/ LM Studio continuam recebendo RAG independente desta flag. |
| ☐ | `test_chatview_shows_a_persistent_indicator_when_rag_is_blocked` | O aviso precisa ser visível o tempo todo que a condição for verdadeira (não um toast que aparece uma vez e nunca mais) - condicionado exatamente ao me… |


### test_rag_chunking_and_grouping.py
**Módulo:** `phoenix_kernel.intelligence.chroma_rag_backend`

Testes de regressão pro achado real do usuário 2026-08-24/28 ("habilitar RAG... ja pode receber qualquer documento e injetar esse conhecimento pra qualquer llm consumir e/ou ler o arquivo de 1000 folhas e usar conhecimento pra responder melhor"). Cobre a parte de phoenix_kernel/i…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_split_into_chunks_empty_text_returns_empty_list` | Split into chunks empty text returns empty list |
| ☐ | `test_split_into_chunks_short_text_is_single_chunk_identical_to_input` | Split into chunks short text is single chunk identical to input |
| ☐ | `test_split_into_chunks_long_multi_paragraph_text_produces_multiple_chunks_within_limit` | Split into chunks long multi paragraph text produces multiple chunks within limit |
| ☐ | `test_split_into_chunks_consecutive_chunks_overlap` | Split into chunks consecutive chunks overlap |
| ☐ | `test_split_into_chunks_single_paragraph_larger_than_max_is_hard_split_with_overlap` | Split into chunks single paragraph larger than max is hard split with overlap |
| ☐ | `test_add_document_chunked_short_content_is_single_chunk_like_before` | Add document chunked short content is single chunk like before |
| ☐ | `test_add_document_chunked_long_content_produces_multiple_chunks_sharing_group_id` | Add document chunked long content produces multiple chunks sharing group id |
| ☐ | `test_add_document_chunked_reindexing_shorter_content_removes_orphan_chunks` | Add document chunked reindexing shorter content removes orphan chunks |
| ☐ | `test_add_document_chunked_rejects_empty_title_or_content` | Add document chunked rejects empty title or content |
| ☐ | `test_add_document_chunked_raises_when_backend_unavailable` | Add document chunked raises when backend unavailable |
| ☐ | `test_list_documents_groups_chunks_back_into_one_row_per_source_document` | List documents groups chunks back into one row per source document |
| ☐ | `test_delete_document_by_group_id_removes_all_chunks_at_once` | Delete document by group id removes all chunks at once |
| ☐ | `test_delete_document_falls_back_to_exact_id_for_legacy_documents_without_group_id` | Delete document falls back to exact id for legacy documents without group id |
| ☐ | `test_delete_document_returns_false_for_nonexistent_id` | Delete document returns false for nonexistent id |
| ☐ | `test_delete_document_raises_when_backend_unavailable` | Delete document raises when backend unavailable |
| ☐ | `test_query_with_scores_returns_empty_list_when_backend_unavailable` | Query with scores returns empty list when backend unavailable |
| ☐ | `test_query_with_scores_returns_empty_list_for_blank_query` | Query with scores returns empty list for blank query |


### test_rag_query_min_score_filter.py
**Módulo:** *(vários módulos)*

Teste de regressão pra auditoria completa 2026-08-28, item "validar o threshold min_score: 0.15 do RAG". Contexto honesto: este ambiente de execução bloqueia o download do modelo de embeddings usado pelo RAG de verdade (tanto a fonte padrão do ChromaDB quanto o Hugging Face Hub d…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_rag_query_filters_hits_below_min_score` | Rag query filters hits below min score |
| ☐ | `test_rag_query_boundary_score_equal_to_min_score_is_kept` | Caso de borda explícito: o filtro usa `>=`, não `>` - um hit com score EXATAMENTE igual a min_score não pode ser descartado. |
| ☐ | `test_rag_query_default_min_score_keeps_everything` | min_score default (0.0, quando o cliente não manda nada) não deve cortar nenhum hit, mesmo um com score 0.0 exato. |
| ☐ | `test_rag_query_negative_min_score_is_clamped_to_zero` | `max(0.0, req.min_score)` protege contra um min_score negativo (bug de cliente, ou tentativa de bypass) virando "aceita tudo, inclusive score negativo… |
| ☐ | `test_rag_query_empty_query_rejected_before_touching_backend` | Rag query empty query rejected before touching backend |
| ☐ | `test_rag_query_backend_unavailable_returns_503` | Rag query backend unavailable returns 503 |


## 🧠 Raciocínio & Arbitragem

*72 testes em 8 arquivo(s).*


### test_arbiter_wiring_contracts.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_api_has_first_gate_before_routes` | Api has first gate before routes |
| ☐ | `test_resident_delegates_resource_decision` | Resident delegates resource decision |
| ☐ | `test_frontend_calls_arbiter_before_legacy_heuristics` | Frontend calls arbiter before legacy heuristics |
| ☐ | `test_node_proxies_arbiter` | Node proxies arbiter |


### test_capability_v4_integration.py
**Módulo:** `phoenix_kernel.licensing.capability_protocol`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_signature_nonce_machine_and_feature` | Signature nonce machine and feature |
| ☐ | `test_tampered_payload_rejected` | Tampered payload rejected |
| ☐ | `test_expired_rejected` | Expired rejected |


### test_execution_arbiter.py
**Módulo:** `phoenix_kernel.orchestration.execution_arbiter`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_unknown_route_is_explicit_passthrough` | Unknown route is explicit passthrough |
| ☐ | `test_chat_is_cpu` | Chat is cpu |
| ☐ | `test_image_generation_is_gpu` | Image generation is gpu |
| ☐ | `test_english_selected_sdxl_command_is_image_generation` | English selected sdxl command is image generation |
| ☐ | `test_english_question_about_image_generation_stays_chat` | English question about image generation stays chat |
| ☐ | `test_raw_stable_diffusion_prompt_is_gpu` | Raw stable diffusion prompt is gpu |
| ☐ | `test_question_about_image_generation_stays_chat` | Question about image generation stays chat |
| ☐ | `test_document_create_phoenix_self_is_grounded_and_gpu_fallback` | Document create phoenix self is grounded and gpu fallback |
| ☐ | `test_short_document_read_is_cpu` | Short document read is cpu |
| ☐ | `test_two_docs_one_xlsx_claims_fill_template` | Two docs one xlsx claims fill template |
| ☐ | `test_document_edit_heavy_gets_gpu_burst_policy` | Document edit heavy gets gpu burst policy |
| ☐ | `test_worker_policy_semantics_are_source_contract` | Worker policy semantics are source contract |


### test_infer_command_bridge.py
**Módulo:** `phoenix_kernel.resident.resident_manager`

Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser contornado" — Seção 3 da diretiva de 20 seções). Este é o achado mais grave da rodada: o comando `infer <prompt>` (ApiEngine.process_command(), acionado por POST /api/command — o caminho de inferência de t…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_run_inference_direct_tracks_model_and_returns_execution_result` | Run inference direct tracks model and returns execution result |
| ☐ | `test_run_inference_direct_does_not_track_model_on_failure` | Run inference direct does not track model on failure |
| ☐ | `test_run_inference_direct_no_runtime_raises_clean_error` | Run inference direct no runtime raises clean error |
| ☐ | `test_infer_command_calls_resident_bridge_not_runtime_execute_directly` | Infer command calls resident bridge not runtime execute directly |
| ☐ | `test_infer_command_surfaces_bridge_failure_as_error_output` | Infer command surfaces bridge failure as error output |
| ☐ | `test_infer_command_without_resident_returns_error_without_crashing` | Infer command without resident returns error without crashing |


### test_llm_reviewer.py
**Módulo:** `phoenix_kernel.documents.evidence_engine`

Testes do revisor LLM — resolve só campos duvidosos, com trava anti-alucinação.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_only_doubtful_fields_reach_the_llm` | Campos confirmed NÃO gastam chamada de LLM; só conflict/ambiguous. |
| ☐ | `test_hallucinated_value_is_rejected` | Valor fora da allowlist é REJEITADO — campo segue para auditoria. |
| ☐ | `test_valid_choice_is_applied_and_promotes_field` | Valid choice is applied and promotes field |
| ☐ | `test_llm_failure_does_not_crash_pipeline` | Se a chamada ao LLM lança, o campo é rejeitado (vai pra auditoria), não derruba a revisão inteira. |
| ☐ | `test_max_fields_limits_llm_calls` | Max fields limits llm calls |
| ☐ | `test_evidence_view_indexes_by_record_id_so_promotion_works` | A view dos canonical precisa indexar por fe.record_id (não canonical_id), senão o revisor resolve mas apply_resolutions não promove nada. |


### test_mission_kernel.py
**Módulo:** `phoenix_kernel.core.models`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_planner_creates_mission_with_correct_steps` | Planner creates mission with correct steps |
| ☐ | `test_kernel_registers_mission_and_sets_waiting_approval` | Kernel registers mission and sets waiting approval |
| ☐ | `test_kernel_approves_active_mission` | Kernel approves active mission |
| ☐ | `test_kernel_rejects_active_mission` | Kernel rejects active mission |
| ☐ | `test_kernel_approve_without_active_mission_raises_error` | Kernel approve without active mission raises error |
| ☐ | `test_to_dict_serialization` | To dict serialization |
| ☐ | `test_each_mission_has_unique_id` | Each mission has unique id |
| ☐ | `test_registered_mission_is_same_instance` | Registered mission is same instance |
| ☐ | `test_status_is_serialized_as_string` | Status is serialized as string |
| ☐ | `test_step_parameters_are_serialized` | Step parameters are serialized |
| ☐ | `test_step_action_is_enum_instance` | Step action is enum instance |
| ☐ | `test_metadata_is_serialized` | Metadata is serialized |
| ☐ | `test_parameters_default_to_empty_dict` | Parameters default to empty dict |


### test_reasoning_engine_think_block_stripping.py
**Módulo:** `phoenix_kernel.intelligence.reasoning_engine`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_extract_json_ignores_brace_mentioned_inside_think_block` | Extract json ignores brace mentioned inside think block |
| ☐ | `test_extract_json_handles_think_block_with_no_braces_inside` | Extract json handles think block with no braces inside |
| ☐ | `test_extract_json_handles_fenced_json_after_think_block` | Extract json handles fenced json after think block |
| ☐ | `test_extract_json_returns_none_when_only_think_block_and_no_json` | Extract json returns none when only think block and no json |
| ☐ | `test_strip_think_block_removes_multiple_blocks_case_insensitively` | Strip think block removes multiple blocks case insensitively |
| ☐ | `test_strip_think_block_is_noop_when_there_is_no_think_tag` | Strip think block is noop when there is no think tag |


### test_resident_research_json_hardening.py
**Módulo:** `phoenix_kernel.intelligence.reasoning_engine`

Testes de regressão para a auditoria 2026-08-20, "Resident Research + llama.cpp JSON hardening" (achado explícito: json_format=True no ExecutionPlan não fazia NADA no LlamaCppDriver - só o OllamaDriver lia esse campo. resident research em llama.cpp dependia 100% da instrução em t…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_extract_pure_json` | Cenário 1 do checklist: resposta JSON pura válida. |
| ☐ | `test_extract_json_with_preamble_text` | Cenário 2: resposta com texto antes do JSON. |
| ☐ | `test_extract_json_in_markdown_fence_with_json_tag` | Cenário 3: resposta com bloco ```json ... ```. |
| ☐ | `test_extract_json_in_markdown_fence_without_json_tag` | Extract json in markdown fence without json tag |
| ☐ | `test_extract_invalid_json_returns_none` | Cenário 4: resposta com JSON inválido (vírgula sobrando, sem valor). |
| ☐ | `test_extract_no_json_at_all_returns_none` | Cenário 5: resposta sem JSON nenhum. |
| ☐ | `test_extract_empty_string_returns_none` | Extract empty string returns none |
| ☐ | `test_extract_json_array_wrapping_one_object_extracts_the_inner_object` | Corrigido depois de rodar o teste pela primeira vez: minha suposição inicial era que um array JSON deveria ser rejeitado (plan_mission() espera um dic… |
| ☐ | `test_extract_json_array_of_scalars_has_no_object_to_extract` | Diferente do caso acima: um array sem nenhum objeto dentro (só escalares) não tem '{' nenhum pra achar - tem que devolver None, não inventar um dict v… |
| ☐ | `test_extract_balanced_braces_ignores_braces_inside_strings` | Bracket-matching tem que ignorar '{' e '}' que aparecem DENTRO de uma string JSON - um "reasoning" com chave literal no texto não pode fechar o objeto… |
| ☐ | `test_extract_prefers_first_valid_candidate_over_malformed_fence` | Se o texto puro já é JSON válido, o resultado tem que ser correto de qualquer forma, não importa qual candidato exatamente ganhou. |
| ☐ | `test_plan_mission_succeeds_on_first_try_no_retry_needed` | Plan mission succeeds on first try no retry needed |
| ☐ | `test_plan_mission_recovers_via_markdown_fence_without_retry` | Plan mission recovers via markdown fence without retry |
| ☐ | `test_plan_mission_retries_after_non_json_then_succeeds` | Cenário 6 do checklist: retry funcionando. Primeira resposta não é JSON de jeito nenhum; segunda (após reprompt) é válida. |
| ☐ | `test_plan_mission_gives_up_cleanly_after_exhausting_retries` | Cenário 7 do checklist - o mais importante: JSON inválido não pode virar missão registrada, mesmo depois de esgotar as tentativas. |
| ☐ | `test_plan_mission_no_retry_on_runtime_failure` | Falha de runtime (rede, processo morto) é uma classe de erro diferente de "resposta não é JSON" - não deve consumir tentativas de retry, só falha dire… |
| ☐ | `test_plan_mission_valid_json_without_steps_or_response_is_rejected` | JSON sintaticamente válido mas sem 'steps' nem 'response' continua sendo rejeitado (comportamento pré-existente, não pode regredir). |
| ☐ | `test_plan_mission_direct_response_conversational_no_mission` | Resposta conversacional (steps vazio, response preenchido) continua devolvendo None mas populando last_response - comportamento pré-existente, não pod… |
| ☐ | `test_plan_mission_uses_llama_cpp_by_default` | Cenário 8 do checklist: resident research usando llama.cpp com json_format=True - confirma que o runtime resolvido é mesmo llama.cpp quando não há hin… |
| ☐ | `test_plan_mission_respects_ollama_hint_without_breaking` | Cenário 9 do checklist: resident research usando Ollama opcional sem quebrar - com text_engine_hint='ollama', o plan_mission ainda usa a mesma blindag… |
| ☐ | `test_llama_cpp_driver_sends_response_format_when_json_format_true` | Llama cpp driver sends response format when json format true |
| ☐ | `test_llama_cpp_driver_omits_response_format_when_not_requested` | Uma chamada comum (chat normal, sem json_format) não deve forçar o backend a produzir JSON - isso quebraria respostas conversacionais de texto livre. |


## 🔌 Drivers & Runtime

*34 testes em 7 arquivo(s).*


### test_llama_cpp_driver_timeout_and_error_detail.py
**Módulo:** `phoenix_kernel.runtime.drivers.llama_cpp`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_fill_spreadsheet_template_direct_passes_timeout_seconds_to_plan` | Garante que resident_manager.py realmente repassa um orçamento real pro driver nesse fluxo específico - sem isso, os testes acima provam que o mecanis… |


### test_llama_cpp_launch_policy.py
**Módulo:** *(vários módulos)*

Regression tests for the 2026-08-30 llama.cpp launch-policy patch. These tests are intentionally dependency-light: they stub Phoenix domain modules so this file can validate the driver's argument construction without booting Phoenix.


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_default_chat_policy_is_unchanged` | Default chat policy is unchanged |
| ☐ | `test_gpu_worker_arguments_are_explicit_and_local` | Gpu worker arguments are explicit and local |
| ☐ | `test_dynamic_port_skips_occupied_port` | Dynamic port skips occupied port |


### test_llama_server_context_size.py
**Módulo:** *(vários módulos)*

PHX-UPDATE (06/09/2026): teste original do achado de 24/08 (8192→16384),
reescrito pra cobrir a segunda rodada do MESMO achado recorrendo
(16384→32768) + o checkbox "Sem limite" no chat. Ver
[INVESTIGACAO_RESPOSTA_CORTADA.md](./INVESTIGACAO_RESPOSTA_CORTADA.md)
para o raciocínio completo — essa segunda rodada, sozinha, não resolvia o
sintoma "resposta cortada sem erro" (causa raiz diferente, ver
`test_reasoning_truncation_fix.mjs` abaixo).

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_llama_server_context_size_is_32768` | Contexto real é 32768 (não mais 16384) |
| ☐ | `test_llama_server_launch_command_has_no_leftover_old_values` | Sem sobra de 8192 nem 16384 na montagem do comando |
| ☐ | `test_aviary_frontend_context_window_uses_real_llama_server_value` | Aviary frontend context window uses real llama server value |
| ☐ | `test_aviary_frontend_no_longer_claims_128000_for_llama_server_unconditionally` | Aviary frontend no longer claims 128000 for llama server unconditionally |
| ☐ | `test_chat_max_tokens_zero_means_unlimited_and_is_omitted_from_payload` | maxTokens=0 ("Sem limite") omite max_tokens da requisição |
| ☐ | `test_parameters_drawer_has_unlimited_checkbox` | Checkbox "Sem limite" presente em ParametersDrawer.tsx |


### platform_source/test_reasoning_truncation_fix.mjs (novo, 06/09/2026)
**Módulo:** `llama_cpp.py`, `server.ts`, `AviaryApp.tsx`

Causa raiz REAL do sintoma "resposta do modelo fica cortada, sem erro, nos
dois provedores" — não era contexto/timeout (isso é outro problema, já
coberto acima). Ver
[INVESTIGACAO_RESPOSTA_CORTADA.md](./INVESTIGACAO_RESPOSTA_CORTADA.md)
para o raciocínio completo, incluindo a correção de rota no meio da
investigação.

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `_build_server_args() passa --jinja explicitamente` | llama-server sempre com --jinja, nunca depende do padrão da build |
| ☐ | `extrai reasoning_content de data.choices[0].message` | server.ts lê o campo separado que o llama-server devolve |
| ☐ | `resposta JSON do chat local inclui campo reasoning` | Campo repassado pro front-end |
| ☐ | `Gemini: thinkingConfig configurado explicitamente` | Nunca deixa no padrão do Google (thinking ligado sem controle) |
| ☐ | `Gemini: reserva de tokens extra pro raciocínio` | maxOutputTokens = maxTokens + 4096, nunca tira do que o usuário pediu |
| ☐ | `Gemini: extrai thought parts da resposta` | candidates[0].content.parts filtrando thought===true |
| ☐ | `Gemini: resposta JSON inclui campo reasoning` | Mesma interface do llama-server, consistente |
| ☐ | `os DOIS caminhos de chat priorizam data.reasoning` | Chat normal E Arena de comparação, ambos corrigidos |
| ☐ | `tag FECHADA: comportamento antigo preservado` | Regressão: caso comum continua funcionando |
| ☐ | `tag ABERTA sem fechar: texto bruto NÃO vaza` | O achado central do bug - tag cortada nunca mais aparece crua na tela |
| ☐ | `tag ABERTA sem fechar: texto antes da tag continua visível` | Resposta parcial válida não é descartada |
| ☐ | `tag ABERTA sem fechar: raciocínio incompleto vai pro thinkingText` | Nunca mostrado como resposta final |
| ☐ | `sem tag nenhuma: responseText passa intacto` | Caso comum (sem raciocínio) não quebra |


### test_ollama_driver_no_fake_success.py
**Módulo:** `phoenix_kernel.runtime.drivers.ollama`

PHX-FIX (auditoria 31/08, achado por agente de varredura ampla, "sucesso fantasma"): `OllamaDriver.start()` retornava `True` incondicionalmente, sem nenhuma checagem real do serviço - e `execute()` reportava SUCCESS mesmo com `message.content` vazio, desde que a chamada HTTP em s…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_start_returns_false_when_ollama_unreachable` | Start returns false when ollama unreachable |
| ☐ | `test_start_returns_true_when_ollama_reachable` | Start returns true when ollama reachable |
| ☐ | `test_execute_fails_on_empty_model_response` | Execute fails on empty model response |
| ☐ | `test_execute_succeeds_on_real_content` | Execute succeeds on real content |


### test_proxy_backend_timeout_alignment.py
**Módulo:** *(vários módulos)*

Teste de regressão pra auditoria 2026-08-21, "corrigir tudo" - resposta a um achado real de uma auditoria externa independente (outra sessão do Claude, lendo o `PHOENIX_3.0_RODADA21.zip` de fora): o AbortController do proxy Node (`platform_source/server.ts`) e o timeout interno d…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_documents_read_and_edit_proxy_has_margin_over_engine_guard` | Documents read and edit proxy has margin over engine guard |
| ☐ | `test_describe_image_proxy_has_margin_over_mtmd_driver_timeout` | Describe image proxy has margin over mtmd driver timeout |
| ☐ | `test_transcribe_proxy_has_margin_over_whisper_driver_timeout` | Transcribe proxy has margin over whisper driver timeout |
| ☐ | `test_benchmark_has_its_own_engine_guard_and_proxy_has_margin_over_it` | Benchmark has its own engine guard and proxy has margin over it |
| ☐ | `test_benchmark_timeout_error_is_controlled_not_a_bare_exception` | Benchmark timeout error is controlled not a bare exception |


### test_runtime_policy_lmstudio_optional.py
**Módulo:** *(vários módulos)*

Teste de regressão pra auditoria 2026-08-20, Target 1 ("Runtime policy / LM Studio opcional / portas corretas"). Achado real, confirmado no log de instalação real anexado pelo usuário e por leitura de código: a instalação da Phoenix tratava alguns componentes 100% OPCIONAIS (LM S…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_is_cli_installed_returns_false_on_filenotfound` | Is cli installed returns false on filenotfound |
| ☐ | `test_is_cli_installed_returns_false_on_arbitrary_exception` | Is cli installed returns false on arbitrary exception |
| ☐ | `test_is_cli_installed_true_when_returncode_zero` | Is cli installed true when returncode zero |
| ☐ | `test_try_start_server_returns_true_immediately_when_already_running` | Try start server returns true immediately when already running |
| ☐ | `test_try_start_server_warns_without_raising_when_absent_and_cli_missing` | Cenário Seção 1/5: LM Studio nao instalado nesta maquina - nunca pode virar um erro que impede o boot, so um aviso claro. |
| ☐ | `test_try_start_server_never_raises_even_if_subprocess_blows_up` | Mesmo se 'lms server start' falhar de um jeito inesperado (exceção genérica no create_subprocess_exec), try_start_server() devolve (False, msg) - nunc… |
| ☐ | `test_try_start_server_offline_after_attempt_still_returns_gracefully` | CLI existe, comando roda, mas o servidor continua sem responder - ainda assim so um aviso, nunca uma exceção. |
| ☐ | `test_lmstudio_is_not_a_valid_text_engine_value` | Lmstudio is not a valid text engine value |
| ☐ | `test_set_text_engine_preference_rejects_lmstudio` | Set text engine preference rejects lmstudio |
| ☐ | `test_text_engine_preference_defaults_to_llama_cpp_when_file_absent` | Text engine preference defaults to llama cpp when file absent |
| ☐ | `test_text_engine_preference_falls_back_to_llama_cpp_when_file_has_lmstudio` | Mesmo se alguém escrever manualmente {"engine":"lmstudio"} no arquivo em disco (fora do fluxo normal), a leitura recusa e cai no default seguro - nunc… |
| ☐ | `test_text_engine_preference_falls_back_to_llama_cpp_on_malformed_json` | Text engine preference falls back to llama cpp on malformed json |
| ☐ | `test_ollama_is_valid_but_never_default_unless_set` | Ollama e uma segunda opcao valida - mas so quando o usuario troca explicitamente (arquivo ausente == llama.cpp, nao ollama). |


### test_source_contracts.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_document_worker_has_correctness_gate_and_dynamic_port` | Document worker has correctness gate and dynamic port |
| ☐ | `test_resident_heavy_document_router_is_fail_closed` | Resident heavy document router is fail closed |
| ☐ | `test_installer_pins_llama_and_preserves_previous_build` | Installer pins llama and preserves previous build |
| ☐ | `test_unlimited_output_is_actually_honored` | Unlimited output is actually honored |


## 🖥️ Hardware & Telemetria

*9 testes em 2 arquivo(s).*


### test_ahde_platform_bridge.py
**Módulo:** `phoenix_kernel.ahde.contracts`

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_ahde_event_history_is_bounded_and_newest_first` | Ahde event history is bounded and newest first |
| ☐ | `test_sensor_normalization_uses_observed_values` | Sensor normalization uses observed values |
| ☐ | `test_ahde_and_report_routes_are_registered` | Ahde and report routes are registered |
| ☐ | `test_system_report_ui_contains_no_fabricated_health_or_hardware` | System report ui contains no fabricated health or hardware |


### test_telemetry_consent_gating.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_cloud_sync_loop_interval_is_60_seconds` | Confirma o "a cada 60s" da pergunta do usuário - CLOUD_SYNC_INTERVAL_SEC é o valor real usado no asyncio.sleep() do loop, não só uma constante solta s… |
| ☐ | `test_network_method_checks_consent_before_any_work` | Cada método público de FirestoreSync que manda ou pede algo ao Firestore precisa começar checando has_consent() e devolvendo cedo (return/return False… |
| ☐ | `test_grant_consent_called_only_from_the_dedicated_accept_route` | grant_consent() é o único jeito de data/telemetry_consent.flag passar a existir - confirma que ele só é invocado a partir da rota HTTP dedicada, e não… |
| ☐ | `test_no_install_or_setup_script_writes_telemetry_consent_flag_directly` | Nenhum script de instalação/setup deveria criar o arquivo de consentimento diretamente (bypassando a rota HTTP e, com isso, a decisão explícita do usu… |
| ☐ | `test_has_consent_checks_the_real_flag_file_not_a_hardcoded_true` | Rede de segurança contra uma regressão boba mas real: alguém trocar `return CONSENT_FLAG.exists()` por `return True` sem querer, o que ligaria telemet… |


## 🌐 Modelos & Catálogo

*41 testes em 7 arquivo(s).*


### test_asset_catalog_download_errors.py
**Módulo:** *(vários módulos)*

Testes de regressão pra auditoria 2026-08-20, Seção 14 do LEIA-ME ("catálogo de imagem/VAE com URLs 401/404"). HISTÓRICO IMPORTANTE (deixado explícito pra não repetir o erro): a Rodada 17 "corrigiu" catalog/assets/flux_vae.json trocando black-forest-labs/FLUX.1-dev por black-fore…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_install_script_flux_vae_url_does_not_use_official_gated_repo` | Install script flux vae url does not use official gated repo |
| ☐ | `test_sdxl_vae_fix_catalog_exists_with_correct_remote_filename` | Sdxl vae fix catalog exists with correct remote filename |
| ☐ | `test_install_script_sdxl_vae_fix_url_matches_real_remote_filename` | Install script sdxl vae fix url matches real remote filename |
| ☐ | `test_http_provider_classifies_401_as_auth_required` | Http provider classifies 401 as auth required |
| ☐ | `test_http_provider_classifies_404_as_dead_link` | Http provider classifies 404 as dead link |
| ☐ | `test_http_provider_success_still_writes_file_and_returns_no_reason` | Http provider success still writes file and returns no reason |
| ☐ | `test_get_asset_exposes_classified_reason_on_404` | Get asset exposes classified reason on 404 |
| ☐ | `test_get_asset_never_attempts_download_when_requires_auth` | Get asset never attempts download when requires auth |
| ☐ | `test_get_asset_success_clears_previous_last_error` | Get asset success clears previous last error |
| ☐ | `test_get_asset_downloads_declared_dependencies_before_main_asset` | Get asset downloads declared dependencies before main asset |


### test_aviary_provider_no_fake_models.py
**Módulo:** *(vários módulos)*

Teste de regressão pra auditoria 2026-08-20, "existem falhas e fallbacks - rastrear e tirar tudo" (achado real, vindo de screenshots + logs de produção do usuário, não hipotético): o usuário selecionou "[OLLAMA] qwen3:8b" no seletor de modelo do chat da Aviary e tomou "Falha ao o…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_local_providers_do_not_ship_with_fabricated_placeholder_models` | Local providers do not ship with fabricated placeholder models |
| ☐ | `test_available_models_filters_out_local_providers_not_confirmed_connected` | Available models filters out local providers not confirmed connected |
| ☐ | `test_scan_all_providers_replaces_model_list_instead_of_unioning_stale_data` | Scan all providers replaces model list instead of unioning stale data |
| ☐ | `test_handle_test_provider_trusts_real_ping_result_even_when_empty` | Handle provider trusts real ping result even when empty |


### test_benchmark_bridge.py
**Módulo:** `phoenix_kernel.resident.resident_manager`

Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser contornado" — Seção 3 da diretiva de 20 seções). Achado: POST /api/benchmark em api_server.py montava o próprio ExecutionPlan (resolvendo o modelo via resident.registry.resolve("chat") só pra citar no plan…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_run_token_benchmark_direct_uses_resolved_chat_model_and_tracks_it` | Run token benchmark direct uses resolved chat model and tracks it |
| ☐ | `test_run_token_benchmark_direct_never_fabricates_metrics_on_failure` | Run token benchmark direct never fabricates metrics on failure |
| ☐ | `test_run_token_benchmark_direct_times_out_with_controlled_error_instead_of_hanging` | Run token benchmark direct times out with controlled error instead of hanging |
| ☐ | `test_run_token_benchmark_direct_no_runtime_fails_cleanly` | Run token benchmark direct no runtime fails cleanly |
| ☐ | `test_benchmark_route_calls_resident_not_runtime_execute_directly` | Benchmark route calls resident not runtime execute directly |
| ☐ | `test_benchmark_route_surfaces_resident_error_as_502` | Benchmark route surfaces resident error as 502 |
| ☐ | `test_benchmark_route_missing_resident_returns_503` | Benchmark route missing resident returns 503 |


### test_ensure_docker_running_waits_properly.py
**Módulo:** *(vários módulos)*

Teste de regressão pra auditoria 2026-08-21: "phoenix vai aguardar docker responder e só depois continuar subindo tudo" - achado real de uso real (log do usuário mostrou "[!] Docker demorou muito para iniciar. Alguns serviços podem não subir." seguido, na mesma respiração, de "[✓…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_wait_window_is_at_least_600_seconds_as_explicitly_requested` | Wait window is at least 600 seconds as explicitly requested |
| ☐ | `test_finds_per_user_docker_desktop_install_when_admin_paths_missing` | Finds per user docker desktop install when admin paths missing |
| ☐ | `test_ensure_docker_running_actually_calls_popen_for_per_user_install` | Ensure docker running actually calls popen for per user install |
| ☐ | `test_popen_failure_returns_false_cleanly_instead_of_crashing_boot` | Popen failure returns false cleanly instead of crashing boot |
| ☐ | `test_returns_true_immediately_when_docker_already_running` | Returns true immediately when docker already running |
| ☐ | `test_returns_false_without_hanging_when_docker_binary_missing` | Returns false without hanging when docker binary missing |
| ☐ | `test_waits_through_the_full_window_and_recovers_if_docker_comes_up_late` | O caso central do achado: Docker demora, mas ACABA respondendo - dentro da janela nova, isso precisa contar como sucesso (o bug antigo desistia aos 60… |
| ☐ | `test_gives_up_after_full_window_without_raising_and_docker_stays_optional` | Mesmo com a janela maior, o Docker continua OPCIONAL - se ele nunca responder, `ensure_docker_running()` precisa devolver False de forma limpa (nunca … |
| ☐ | `test_main_block_captures_the_return_value_instead_of_discarding_it` | Main block captures the return value instead of discarding it |


### test_http_provider_content_length_validation.py
**Módulo:** *(vários módulos)*

Teste de regressão pra um bug real achado nesta sessão (2026-08-23), durante o teste end-to-end do novo auto-download do Kokoro (catalog/assets/ kokoro_model.json, endpoint /api/tts/kokoro/download): um download de verdade contra o GitHub (não simulado) terminou o loop de leitura…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_http_provider_rejects_truncated_download_when_content_length_known` | Http provider rejects truncated download when content length known |
| ☐ | `test_http_provider_accepts_complete_download_matching_content_length` | Http provider accepts complete download matching content length |
| ☐ | `test_http_provider_skips_validation_when_no_content_length_header` | Http provider skips validation when no content length header |
| ☐ | `test_get_asset_never_caches_a_truncated_download` | Get asset never caches a truncated download |


### test_installer_installs_test_dependencies.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_common_installer_installs_pytest_and_pytest_asyncio` | Common installer installs pyand pyasyncio |
| ☐ | `test_pytest_install_happens_inside_the_activated_venv_block` | Pyinstall happens inside the activated venv block |
| ☐ | `test_requirements_txt_also_lists_pytest_for_ci_and_manual_setup` | Requirements txt also lists pyfor ci and manual setup |


### test_web_search_route.py
**Módulo:** *(vários módulos)*

Teste de regressão pra achado real do usuário (2026-08-24, screenshot): digitou "pesquisar acidente com 2 helicópteros no rj em 2026" no chat normal da Aviary, e o qwen3-8b respondeu direto da própria memória de treino ("a data de 2026 ainda não chegou, não há registros") - sem N…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_web_search_route_returns_real_results_on_success` | Web search route returns real results on success |
| ☐ | `test_web_search_route_passes_through_no_results_as_success` | Web search route passes through no results as success |
| ☐ | `test_web_search_route_surfaces_real_failure_as_http_error_never_fake_success` | Web search route surfaces real failure as http error never fake success |
| ☐ | `test_web_search_route_rejects_empty_query_before_calling_search` | Web search route rejects empty query before calling search |


## 🚀 Release & Higiene

*14 testes em 3 arquivo(s).*


### test_pdf_extraction_no_silent_ocr.py
**Módulo:** `phoenix_kernel.documents.engine`

Teste de regressão pra auditoria 2026-08-20, "existem falhas e fallbacks - rastrear e tirar tudo" (achado real, vindo de log de produção real do usuário, não de leitura de código): `/api/documents/read` travava no timeout de 240s do `[DirectDocumentBridge]` (`resident_manager.py`…


| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_normal_pdf_still_extracts_native_text_correctly` | Normal pdf still extracts native text correctly |
| ☐ | `test_textless_pdf_fails_fast_with_clear_error_instead_of_silent_ocr` | Textless pdf fails fast with clear error instead of silent ocr |
| ☐ | `test_tesseract_ocr_backend_is_never_invoked_for_textless_pdf` | Prova mais direta que o achado real do log de produção não se repete: trava o próprio backend de OCR do pymupdf4llm (tesseract_api.exec_ocr) pra explo… |
| ☐ | `test_source_explicitly_disables_pymupdf4llm_implicit_ocr_fallback` | Guarda de regressão por leitura de fonte: mesmo que o comportamento acima passe por acaso numa versão futura do pymupdf4llm, o código-fonte precisa co… |


### test_release_hygiene_never_publish.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_clean_tree_passes` | Clean tree passes |
| ☐ | `test_flags_private_server_reference_directory` | Flags private server reference directory |
| ☐ | `test_flags_nested_private_server_reference_directory` | A pasta pode estar em qualquer profundidade (ex: dentro de um subdiretório de patches/arquivo) - a checagem usa rglob, não só o nível raiz. |
| ☐ | `test_flags_before_hotfix_backup_file` | Flags before hotfix backup file |
| ☐ | `test_does_not_flag_unrelated_files` | Does not flag unrelated files |
| ☐ | `test_skips_git_and_node_modules_directories` | Mesmo se um clone/checkout tiver o nome dentro de .git ou node_modules (empacotado por outra dependência, por exemplo), não é isso que a checagem quer… |
| ☐ | `test_full_check_exits_nonzero_when_never_publish_path_present` | Teste de integração leve: roda o fluxo principal (main()) contra a árvore temporária e confere que o processo falharia de verdade (código de saída 1) … |


### test_release_hygiene_skips_venv.py
**Módulo:** *(vários módulos)*

| ☐ | Teste | Valida |
|---|-------|--------|
| ☐ | `test_secret_scan_skips_venv_style_directories` | Arquivo de biblioteca pip legítima com marcador de credencial no próprio código-fonte (ex.: google-auth definindo a constante de nome de campo "privat… |
| ☐ | `test_secret_scan_still_flags_real_secret_outside_venv` | Confirma que ignorar .venv não é um buraco que também esconde segredo de verdade fora dele - o mesmo arquivo, fora de uma pasta de venv, continua send… |
| ☐ | `test_self_is_excluded_from_its_own_secret_content_scan` | PHX-FIX (achado do usuário 2026-08-28): este próprio arquivo de teste escreve os marcadores falsos de credencial como literais de string no seu código… |
