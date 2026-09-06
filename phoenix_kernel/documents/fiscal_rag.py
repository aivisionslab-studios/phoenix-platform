"""RAG Fiscal — base consultável de NCM/CEST a partir de dados JÁ AUDITADOS.

O problema que resolve: o Smart Filler deixa NCM/CEST em branco quando o
documento não os traz, porque inventar código fiscal é risco tributário. Mas
a empresa JÁ classificou milhares de produtos corretamente — esse conhecimento
existe, só não estava sendo reaproveitado. Este módulo transforma os catálogos
auditados numa base consultável: dado um produto novo ("Argamassa AC2 20kg"),
encontra produtos semelhantes já classificados e sugere o NCM/CEST deles.

Diferença crucial para "chutar": a sugestão vem de um produto REAL já
auditado, com a descrição da fonte e um score de similaridade. Nunca é uma
invenção — é uma recuperação. E continua passando pela auditoria humana antes
de virar verdade (o campo entra como "sugerido", não "confirmado").

Duas implementações de similaridade:
  - por padrão, um matcher determinístico por tokens (sem dependências, sempre
    funciona, testável) — bom para NCM, onde produtos da mesma família (mesma
    palavra-chave: "argamassa", "tinta") quase sempre compartilham o código;
  - opcionalmente, o ChromaRagBackend da Phoenix (embeddings semânticos), para
    casos onde a descrição varia mas o produto é o mesmo.

O NCM/CEST recuperado passa pelos validadores de formato do Normalizer antes
de ser oferecido — uma entrada malformada na base nunca contamina a sugestão.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from phoenix_kernel.documents.normalizer import normalize_ncm, normalize_cest

# stopwords de descrição de produto que não ajudam a distinguir família fiscal
_STOP = {
    "de", "da", "do", "para", "com", "e", "a", "o", "em", "the", "kg", "g", "ml",
    "l", "cm", "mm", "un", "und", "litros", "litro", "premium", "profissional",
}


def _tokens(text: str) -> set[str]:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOP and not w.isdigit()}


@dataclass
class FiscalEntry:
    """Um produto já classificado que serve de referência."""
    description: str
    ncm: str = ""
    cest: str = ""
    tokens: set = field(default_factory=set)
    source: str = ""  # de qual catálogo veio


@dataclass
class FiscalSuggestion:
    """O que a base devolve para um produto consultado — sempre com de onde
    veio e quão parecido é, para a auditoria humana julgar."""
    field_type: str          # "ncm" ou "cest"
    value: str
    confidence: float        # 0..1, do score de similaridade
    matched_description: str  # o produto de referência que gerou a sugestão
    source: str
    status: str = "suggested"  # nunca "confirmed" — precisa de auditoria


class FiscalRAG:
    """Base fiscal consultável. Construída a partir de linhas de catálogo já
    auditadas; consultada por descrição de produto novo."""

    def __init__(self) -> None:
        self._entries: list[FiscalEntry] = []
        # índice invertido token -> entradas, para consulta rápida
        self._by_token: dict[str, list[int]] = {}

    def add_entry(self, description: str, ncm: str = "", cest: str = "", source: str = "") -> bool:
        """Adiciona um produto de referência. Só entra se tiver descrição e ao
        menos um código fiscal com FORMATO válido (base suja não ajuda ninguém).
        Devolve True se entrou."""
        desc = str(description or "").strip()
        if not desc:
            return False
        ncm_norm = normalize_ncm(ncm)
        cest_norm = normalize_cest(cest)
        ncm_val = str(ncm_norm.normalized) if ncm_norm.valid else ""
        cest_val = str(cest_norm.normalized) if cest_norm.valid else ""
        if not ncm_val and not cest_val:
            return False
        toks = _tokens(desc)
        if not toks:
            return False
        idx = len(self._entries)
        self._entries.append(FiscalEntry(desc, ncm_val, cest_val, toks, source))
        for tok in toks:
            self._by_token.setdefault(tok, []).append(idx)
        return True

    def build_from_rows(self, rows: list[dict], *, source: str = "",
                        desc_col: str = "Descrição", ncm_col: str = "NCM",
                        cest_col: str = "CEST") -> int:
        """Alimenta a base a partir de linhas de um catálogo auditado. Devolve
        quantas entradas de referência foram criadas."""
        n = 0
        for row in rows:
            if self.add_entry(row.get(desc_col, ""), row.get(ncm_col, ""),
                              row.get(cest_col, ""), source):
                n += 1
        return n

    def _similarity(self, query_tokens: set[str], entry: FiscalEntry) -> float:
        """Jaccard ponderado: interseção sobre união dos tokens. Simples,
        determinístico, e suficiente para agrupar por família de produto."""
        if not query_tokens or not entry.tokens:
            return 0.0
        inter = len(query_tokens & entry.tokens)
        union = len(query_tokens | entry.tokens)
        return inter / union if union else 0.0

    def query(self, description: str, *, field_type: str = "ncm",
              min_confidence: float = 0.34, top_k: int = 3) -> list[FiscalSuggestion]:
        """Consulta a base por descrição e devolve as melhores sugestões de
        NCM ou CEST, ordenadas por similaridade. Uma sugestão só sai acima de
        `min_confidence` — abaixo disso, é melhor deixar em branco para
        auditoria do que oferecer um palpite fraco.

        Se as top entradas concordam no MESMO valor, a confiança sobe (várias
        referências independentes dizendo o mesmo código é sinal forte)."""
        qt = _tokens(description)
        if not qt:
            return []
        # candidatos: só entradas que compartilham ao menos um token (via índice)
        cand_idx = set()
        for tok in qt:
            cand_idx.update(self._by_token.get(tok, []))

        scored = []
        for idx in cand_idx:
            entry = self._entries[idx]
            value = entry.ncm if field_type == "ncm" else entry.cest
            if not value:
                continue
            sim = self._similarity(qt, entry)
            if sim >= min_confidence:
                scored.append((sim, entry, value))
        if not scored:
            return []
        scored.sort(key=lambda x: x[0], reverse=True)

        # consenso: se o valor top se repete entre as melhores, reforça
        top_values = Counter(v for _, _, v in scored[:5])
        best_value, best_count = top_values.most_common(1)[0]

        suggestions = []
        seen_values = set()
        for sim, entry, value in scored[:top_k]:
            if value in seen_values:
                continue
            seen_values.add(value)
            conf = sim
            if value == best_value and best_count >= 2:
                conf = min(1.0, sim + 0.15)  # bônus de consenso
            suggestions.append(FiscalSuggestion(
                field_type=field_type, value=value, confidence=round(conf, 3),
                matched_description=entry.description, source=entry.source,
            ))
        return suggestions

    def suggest_for_row(self, row: dict, *, min_confidence: float = 0.34) -> dict:
        """Conveniência: para uma linha de produto, devolve as melhores
        sugestões de NCM e CEST que ainda estão vazios na linha. NUNCA
        sobrescreve um valor já presente. Devolve {field_type: FiscalSuggestion}."""
        out = {}
        desc = row.get("Descrição", "")
        for ft, col in [("ncm", "NCM"), ("cest", "CEST")]:
            cur = row.get(col)
            if cur is None or (isinstance(cur, str) and not cur.strip()):
                sugg = self.query(desc, field_type=ft, min_confidence=min_confidence, top_k=1)
                if sugg:
                    out[ft] = sugg[0]
        return out

    def __len__(self) -> int:
        return len(self._entries)
