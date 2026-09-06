"""Phoenix Execution Arbiter — autoridade única de intenção + recursos.

Princípio arquitetural:

    REQUEST
      -> ARBITER (claim / intent / grounding / executor / resource policy)
      -> EXECUTOR
      -> DRIVER

Os executores não escolhem CPU/GPU e não reinterpretam intenção. Eles apenas
executam a decisão recebida. Quando o árbitro devolve NOT_CLAIMED, o fluxo
legado está explicitamente autorizado a continuar sem interferência.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
import os
import re
import unicodedata
from typing import Any, Iterable


class ClaimState(str, Enum):
    CLAIMED = "claimed"
    NOT_CLAIMED = "not_claimed"
    REJECTED = "rejected"


class ResourcePolicy(str, Enum):
    CPU = "cpu"
    GPU = "gpu"
    HYBRID = "hybrid"
    GPU_WITH_CPU_FALLBACK = "gpu_with_cpu_fallback"
    CPU_WITH_GPU_BURST = "cpu_with_gpu_burst"
    LEGACY = "legacy"


@dataclass(frozen=True)
class IntentDecision:
    claim: ClaimState
    intent: str = "unknown"
    executor: str = "legacy"
    grounding: str = "legacy"
    resource_policy: ResourcePolicy = ResourcePolicy.LEGACY
    confidence: float = 0.0
    reason: str = ""
    subject: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def claimed(self) -> bool:
        return self.claim == ClaimState.CLAIMED

    @property
    def legacy_allowed(self) -> bool:
        return self.claim == ClaimState.NOT_CLAIMED

    @property
    def rejected(self) -> bool:
        return self.claim == ClaimState.REJECTED

    @property
    def allows_cpu_fallback(self) -> bool:
        return self.resource_policy in {
            ResourcePolicy.GPU_WITH_CPU_FALLBACK,
            ResourcePolicy.HYBRID,
            ResourcePolicy.CPU_WITH_GPU_BURST,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["claim"] = self.claim.value
        data["resource_policy"] = self.resource_policy.value
        data["claimed"] = self.claimed
        data["legacy_allowed"] = self.legacy_allowed
        data["rejected"] = self.rejected
        return data


# PHX-FIX (31/08): limiar simples pra separar documento "leve" (CPU puro,
# sem motivo pra arriscar Vulkan) de "pesado" (GPU_WITH_CPU_FALLBACK - só
# vale a pena tentar GPU quando há volume real de conteúdo pra processar).
_HEAVY_SOURCE_CHARS_THRESHOLD = 4000


class ExecutionArbiter:
    """Deterministic first authority for user-intent/resource routing.

    LLMs can later help with semantic microtasks, but they never get authority
    to choose a runtime or to silently reinterpret which Phoenix subsystem was
    requested.
    """

    _DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx", ".md", ".txt"}
    _AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".webm"}
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}

    _SELF_TERMS = (
        "phoenix engine", "phoenix aviary", "aviary platform",
        "phoenix aviary platform", "aivisionslab", "ai visions lab",
        "projeto phoenix", "este projeto phoenix",
    )

    _WEB_RE = re.compile(
        r"\b(pesquis\w*|busqu\w*|procure\w*|search\b|web\b|internet\b|dados\s+atuais|informa[cç][oõ]es\s+atuais)\b",
        re.I,
    )
    _IMAGE_GEN_RE = re.compile(
        r"\b(gere|gerar|crie|criar|fa[çc]a|produza|desenhe|renderize|"
        r"generate|create|draw|render|produce)\b.*\b("
        r"imagem|imagens|foto|fotos|figura|ilustra[cç][aã]o|arte|poster|p[oô]ster|"
        r"image|images|picture|pictures|illustration|artwork)\b",
        re.I,
    )
    # PHX-FIX (auditoria 2026-09-02, achado real): o teste físico enviou
    # "a lovely cat, detailed fur, studio lighting" e "a futuristic Sao Paulo
    # cityscape at night, neon lights, cinematic, 8k" - AMBOS caíram em chat
    # (Qwen devolveu Markdown, GPU ~3%) porque o regex antigo só reconhecia
    # "cinematic lighting/composition" (não "cinematic" solto) e não tinha
    # "studio lighting", "detailed fur", "neon lights". Termos comuns de
    # prompt de difusão adicionados abaixo; a barra de 2 magic_hits + tags
    # LoRA (em _looks_like_raw_image_prompt) evita falso-positivo em frase
    # técnica comum.
    _IMAGE_PROMPT_MAGIC_RE = re.compile(
        r"\b(8k|4k|hyper-?detailed|ultra-?detailed|highly detailed|sharp focus|"
        r"cinematic(?:\s+(?:lighting|composition|shot|photography))?|"
        r"trending on artstation|artstation|"
        r"octane render|unreal engine|concept art|masterpiece|volumetric (?:lighting|smoke)|"
        r"god rays|photorealistic|ultra realistic|digital painting|"
        r"dramatic (?:lighting|rim lighting)|intricate (?:detail|feather detail)|"
        r"studio (?:lighting|portrait|photography)|detailed fur|detailed skin|"
        r"neon lights?|bokeh|depth of field|golden hour|"
        r"wide[\s-]?angle|close[\s-]?up|full body shot|"
        r"soft lighting|rim lighting|backlighting|"
        r"hyperrealistic|photo-?realistic|award-?winning photo(?:graphy)?)\b",
        re.I,
    )
    # PHX-FIX (2026-09-02): tags LoRA/embedding são assinatura inequívoca de
    # prompt de difusão - nenhuma pergunta técnica escreve "<lora:x:0.8>".
    _IMAGE_TAG_RE = re.compile(r"<(?:lora|lyco|embedding|hypernet|ti):[^>]+>", re.I)
    _QUESTION_RE = re.compile(
        r"\?|\b(o que|como|por que|porque|qual|quando|onde|quem|ser[aá] que|"
        r"why|how|what|when|where|who|explain|explique)\b",
        re.I,
    )
    _OCR_RE = re.compile(r"\b(ocr|extrair?\s+(o\s+)?texto|ler\s+o\s+texto|texto\s+da\s+imagem)\b", re.I)
    _TRANSCRIBE_RE = re.compile(r"\b(transcrev\w*|transcri[cç][aã]o|whisper)\b", re.I)
    _DOC_CREATE_RE = re.compile(r"\b(cri[ae]|gere|gerar|produza|monte|exporte|salve)\b.*\b(pdf|docx|word|xlsx|excel|planilha|pptx|powerpoint|markdown|\bmd\b|\btxt\b|documento|arquivo|relat[oó]rio)\b", re.I)
    _DOC_EDIT_RE = re.compile(r"\b(edit\w*|corrij\w*|corrig\w*|reescrev\w*|reformul\w*|revis\w*|altere|modifiqu\w*|ajuste|transforme|converta)\b", re.I)

    @staticmethod
    def normalize(text: str) -> str:
        raw = unicodedata.normalize("NFKD", str(text or "").lower())
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", raw).strip()

    @classmethod
    def _looks_like_raw_image_prompt(cls, text: str) -> bool:
        """Reconhece prompts visuais em tags, mesmo sem 'gere uma imagem'.

        O frontend já possuía esta proteção, mas uma decisão CLAIMED como
        ``chat`` do árbitro tem precedência sobre heurísticas locais. A regra
        precisa viver aqui, na autoridade de intenção, para o prompt não cair
        no Qwen e produzir apenas uma descrição textual.
        """
        raw = text or ""
        # Tag LoRA/embedding é assinatura inequívoca - dispensa qualquer
        # outra checagem e ignora até a heurística de pergunta (ninguém
        # pergunta "como funciona <lora:x>").
        if cls._IMAGE_TAG_RE.search(raw):
            return True
        if cls._QUESTION_RE.search(raw):
            return False
        comma_segments = len(raw.split(","))
        magic_hits = len(cls._IMAGE_PROMPT_MAGIC_RE.findall(raw))
        # PHX-FIX (2026-09-02): a barra antiga (>=4 segmentos E >=2 hits)
        # rejeitava os dois prompts reais do teste físico. Duas formas de
        # aceitar agora, ambas exigindo estrutura de prompt (vírgulas) +
        # vocabulário visual, sem deixar passar frase técnica solta:
        #   - prompt curto e denso: 3+ segmentos e 2+ termos visuais
        #     ("a lovely cat, detailed fur, studio lighting" = 3 seg, 2 hits)
        #   - prompt longo: 4+ segmentos e ao menos 1 termo visual
        #     ("...cityscape at night, neon lights, cinematic, 8k" = 4 seg, 3 hits)
        return (comma_segments >= 3 and magic_hits >= 2) or (comma_segments >= 4 and magic_hits >= 1)

    @classmethod
    def _has_direct_image_command(cls, text: str) -> bool:
        """Reconhece comandos PT/EN sem transformar dúvidas em geração."""
        clauses = [part for part in re.split(r"(?<=[.!?])\s*", text or "") if part.strip()]
        return any(
            cls._IMAGE_GEN_RE.search(clause) and not cls._QUESTION_RE.search(clause)
            for clause in (clauses or [text or ""])
        )

    @staticmethod
    def _attachment_exts(attachments: Iterable[Any] | None) -> list[str]:
        out: list[str] = []
        for item in attachments or []:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("filename") or "")
            else:
                name = str(getattr(item, "name", "") or getattr(item, "filename", ""))
            dot = name.rfind(".")
            out.append(name[dot:].lower() if dot >= 0 else "")
        return out

    def preflight_path(self, path: str, method: str = "POST") -> IntentDecision:
        """Zero-body interception used before legacy route handlers execute."""
        p = (path or "").rstrip("/").lower()
        mapping = {
            "/api/generate-image": ("image_generation", "image_pipeline", ResourcePolicy.GPU),
            "/api/describe-image": ("image_vision", "vision_pipeline", ResourcePolicy.CPU),
            "/api/transcribe": ("audio_transcribe", "speech_pipeline", ResourcePolicy.CPU),
            "/api/documents/read": ("document_read", "document_pipeline", ResourcePolicy.CPU),
            "/api/documents/ingest": ("document_read", "document_pipeline", ResourcePolicy.CPU),
            "/api/documents/edit": ("document_edit", "document_pipeline", ResourcePolicy.CPU),
            "/api/documents/create": ("document_create", "document_pipeline", ResourcePolicy.CPU),
            "/api/documents/fill-template": ("document_fill_template", "document_pipeline", ResourcePolicy.CPU),
            "/api/dual-collab": ("dual_collaboration", "collaboration_pipeline", ResourcePolicy.HYBRID),
        }
        if p in mapping:
            intent, executor, resource = mapping[p]
            return IntentDecision(
                claim=ClaimState.CLAIMED,
                intent=intent,
                executor=executor,
                grounding="pending_body_analysis",
                resource_policy=resource,
                confidence=1.0,
                reason=f"rota Phoenix gerenciada: {p}",
            )
        return IntentDecision(
            claim=ClaimState.NOT_CLAIMED,
            intent="legacy_route",
            executor="legacy",
            grounding="legacy",
            resource_policy=ResourcePolicy.LEGACY,
            confidence=1.0,
            reason="árbitro não foi requisitado para esta rota; fluxo legado liberado",
        )

    def intercept(
        self,
        text: str = "",
        *,
        attachments: Iterable[Any] | None = None,
        requested_operation: str | None = None,
        output_format: str | None = None,
        source_chars: int = 0,
        max_tokens: int | None = None,
        unlimited_output: bool = False,
        use_web: bool = False,
        runtime_hint: str | None = None,
    ) -> IntentDecision:
        """Resolve claim, semantic intent, grounding, executor and CPU/GPU policy."""
        normalized = self.normalize(text)
        exts = self._attachment_exts(attachments)
        has_doc = any(ext in self._DOC_EXTS for ext in exts)
        has_audio = any(ext in self._AUDIO_EXTS for ext in exts)
        has_image = any(ext in self._IMAGE_EXTS for ext in exts)
        web_requested = bool(use_web or self._WEB_RE.search(text or ""))
        self_subject = any(term in normalized for term in self._SELF_TERMS)

        op = self.normalize(requested_operation or "")
        if not op:
            doc_exts = [ext for ext in exts if ext in self._DOC_EXTS]
            if len(doc_exts) == 2 and doc_exts.count(".xlsx") == 1:
                op = "document_fill_template"
            elif has_audio or self._TRANSCRIBE_RE.search(text or ""):
                op = "audio_transcribe"
            elif has_image and self._OCR_RE.search(text or ""):
                op = "image_ocr"
            elif has_image:
                op = "image_vision"
            elif self._has_direct_image_command(text or "") or self._looks_like_raw_image_prompt(text or ""):
                op = "image_generation"
            elif self._DOC_CREATE_RE.search(text or ""):
                op = "document_create" if not has_doc else "document_transform"
            elif has_doc and self._DOC_EDIT_RE.search(text or ""):
                op = "document_edit"
            elif has_doc:
                op = "document_read"
            elif text.strip():
                op = "chat"
            else:
                return IntentDecision(
                    claim=ClaimState.NOT_CLAIMED,
                    intent="unknown",
                    executor="legacy",
                    grounding="legacy",
                    resource_policy=ResourcePolicy.LEGACY,
                    confidence=1.0,
                    reason="nenhuma intenção gerenciada detectada; fluxo legado liberado",
                )

        aliases = {
            "read": "document_read", "edit": "document_edit", "create": "document_create",
            "transform": "document_transform", "fill_template": "document_fill_template",
            "image": "image_generation", "transcribe": "audio_transcribe",
            "ocr": "image_ocr", "vision": "image_vision", "chat": "chat",
        }
        op = aliases.get(op, op)

        if op in {"document_read", "document_edit", "document_create", "document_transform", "document_fill_template", "document_heavy_semantic"}:
            if self_subject:
                subject = "phoenix_self"
                grounding = "internal_project_state+web" if web_requested else "internal_project_state"
                if has_doc:
                    grounding = "attachment+" + grounding
            elif has_doc:
                subject = "attached_document"
                grounding = "attachment+web" if web_requested else "attachment"
            elif web_requested:
                subject = "external_topic"
                grounding = "web"
            else:
                subject = "general"
                grounding = "model_knowledge"

            # PHX-FIX (31/08): esta rodada tinha colapsado TODO documento
            # pra CPU incondicional, indiferente de carga/operação -
            # exatamente o oposto do bug antigo ("GPU sempre"), mas ainda
            # errado: documento pesado/preenchimento de template/pergunta
            # sobre a própria Phoenix têm caminho GPU_WITH_CPU_FALLBACK
            # real e testado (ver PHOENIX_GPU_ONLY_EXCLUSIVE_POLICY.md) -
            # nunca usá-lo desperdiça a chance de resposta mais rápida
            # quando o self-test aprova, sem nenhum ganho de segurança
            # (o self-test continua sendo o gate de correctness de
            # qualquer forma). Documento leve continua CPU puro.
            is_heavy = (
                op in {"document_fill_template", "document_heavy_semantic"}
                or unlimited_output
                or self_subject
                or source_chars >= _HEAVY_SOURCE_CHARS_THRESHOLD
            )
            if is_heavy:
                resource = ResourcePolicy.GPU_WITH_CPU_FALLBACK
                why = "documento pesado/preenchimento de template/auto-referente: tenta GPU com self-test, cai pra CPU se rejeitado"
            else:
                resource = ResourcePolicy.CPU
                why = "documento leve validado em CPU; GPU reservada para carga pesada/imagem"

            return IntentDecision(
                claim=ClaimState.CLAIMED,
                intent=op,
                executor="document_pipeline",
                grounding=grounding,
                resource_policy=resource,
                confidence=1.0 if requested_operation else 0.92,
                reason=why,
                subject=subject,
                metadata={"output_format": output_format or "", "web_requested": web_requested},
            )

        table = {
            "chat": ("chat_pipeline", "conversation", ResourcePolicy.CPU),
            "image_generation": ("image_pipeline", "prompt", ResourcePolicy.GPU),
            "image_vision": ("vision_pipeline", "attachment", ResourcePolicy.CPU),
            "image_ocr": ("vision_pipeline", "attachment", ResourcePolicy.CPU),
            "audio_transcribe": ("speech_pipeline", "attachment", ResourcePolicy.CPU),
            "dual_collaboration": ("collaboration_pipeline", "conversation", ResourcePolicy.HYBRID),
        }
        if op in table:
            executor, grounding, resource = table[op]
            return IntentDecision(
                claim=ClaimState.CLAIMED,
                intent=op,
                executor=executor,
                grounding=grounding,
                resource_policy=resource,
                confidence=1.0 if requested_operation else 0.95,
                reason="intenção Phoenix gerenciada",
                subject="phoenix_self" if self_subject else "general",
            )

        return IntentDecision(
            claim=ClaimState.NOT_CLAIMED,
            intent=op or "unknown",
            executor="legacy",
            grounding="legacy",
            resource_policy=ResourcePolicy.LEGACY,
            confidence=1.0,
            reason="árbitro não foi requisitado/chamado para esta intenção; fluxo legado liberado",
        )


default_execution_arbiter = ExecutionArbiter()
