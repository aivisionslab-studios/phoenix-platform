"""Smart Filler — a Phoenix raciocinando e preenchendo campos vazios.

Esta é a camada que faz, em Python, o mesmo raciocínio que um operador humano
faz ao "terminar" um catálogo: olhar cada produto, deduzir o que é regra,
gerar o conteúdo que falta, e — o mais importante — SABER QUANDO NÃO PREENCHER
(campo fiscal que exige classificação real, ou produto sem nome de verdade).

Três camadas, na ordem em que rodam sobre cada linha:

  1. DERIVAÇÃO (determinística, segura): um campo vazio cujo valor é dedutível
     de OUTRO campo da mesma linha, de um padrão sequencial, ou do valor
     dominante da coluna. Ex.: Origem vazia -> "NACIONAL"; Categoria PDV vazia
     -> copia de "Categoria na Loja Virtual"; Código Interno vazio -> próximo
     da série "PROD###". Nunca inventa — só propaga o que já é verdade.

  2. GERAÇÃO por categoria (conteúdo novo): Tags, Especificações, Itens
     Inclusos, Modelo — construídos a partir do nome + categoria + atributos
     já presentes (marca, tamanho, dimensões, peso). Determinístico por
     padrão; um LLM opcional pode reescrever com mais fluência, mas o
     conteúdo-base sempre existe sem ele.

  3. GUARDA-FISCAL (o "saber não preencher"): NCM, CFOP, CEST NUNCA recebem
     chute — errar gera imposto errado. Um CEST vazio pode ser CORRETO (nem
     todo produto está no regime de ST). Produtos genéricos sem nome real
     ("Produto 61") não são categorizados nem descritos. Esses casos vão para
     um relatório de pendências (a "aba de auditoria" do preenchimento), nunca
     para um valor inventado.

O motor opera sobre linhas como dict {header_da_coluna: valor}, então serve
tanto para o pipeline (CanonicalRecord -> linha) quanto para terminar uma
planilha já existente célula a célula. Cada regra declara de quais colunas
depende e qual produz, então a ordem de aplicação é resolvida sozinha.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# PHX-NEW (2026-09-06, achado real do usuário com um preenchimento de
# planilha de verdade em produção: as pendências fiscais - "sugestão:
# tal NCM" - eram calculadas certinho, mas nunca chegavam a lugar
# nenhum visível no arquivo final entregue; só uma CONTAGEM
# (len(report.pending)) sobrevivia até o resultado da API, a lista real
# com a sugestão de cada linha era descartada). Reaproveita a MESMA aba
# de auditoria (_PHOENIX_AUDIT) que o pipeline determinístico mais novo
# (output_writer.py) já usa pra conflitos de marca/preço/dimensão -
# mesmo formato, uma aba só, em vez de inventar uma segunda convenção.
from phoenix_kernel.documents.output_writer import _AUDIT_SHEET_NAME, _AUDIT_HEADERS, AuditRow


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _ci_find_key(row: dict, target: str) -> Optional[str]:
    """Acha a chave REAL do dict `row` que corresponde a `target`, ignorando
    maiúsculas/minúsculas. PHX-FIX (achado real): templates reais variam o
    casing dos cabeçalhos ("Tags" vs "TAGS", "Descrição do Produto" vs
    "DESCRIÇÃO DO PRODUTO"). Sem isso, o smart_filler comparava a chave
    exata e SILENCIOSAMENTE deixava de preencher 226 de 231 produtos reais
    num template em maiúsculo — sem erro, sem aviso, só ficava vazio."""
    target_norm = target.strip().lower()
    for k in row.keys():
        if isinstance(k, str) and k.strip().lower() == target_norm:
            return k
    return None


def _ci_get(row: dict, target: str):
    """Lê um valor do row por nome de coluna, ignorando maiúsculas/minúsculas."""
    key = _ci_find_key(row, target)
    return row.get(key) if key else None


def _name_core(desc: str) -> str:
    """Parte técnica do nome (antes do travessão de slogan)."""
    return re.split(r"\s+[–—-]\s+", str(desc or ""), 1)[0].strip()


def _size_token(desc: str) -> str:
    m = re.search(r"(\d+[.,]?\d*)\s*(kg|g|ml|l|litros?|cm|mm|\"|m²|un|maço)\b", str(desc or ""), re.I)
    return m.group(0) if m else ""


def _is_placeholder_name(desc: str) -> bool:
    """'Produto 61', 'Produto 62' — nome genérico sem informação real."""
    d = str(desc or "").strip()
    return bool(re.fullmatch(r"produto\s+\d+", d, re.I))


# ---------------------------------------------------------------------------
# resultado
# ---------------------------------------------------------------------------

@dataclass
class FillReport:
    filled_by_rule: dict = field(default_factory=dict)      # coluna -> contagem
    filled_by_generation: dict = field(default_factory=dict)
    left_blank_fiscal: dict = field(default_factory=dict)   # coluna -> contagem (guarda-fiscal)
    left_blank_placeholder: int = 0                          # linhas 'Produto NN' puladas
    pending: list = field(default_factory=list)             # (linha, coluna, motivo)

    def _bump(self, d: dict, key: str) -> None:
        d[key] = d.get(key, 0) + 1


# campos que a guarda-fiscal NUNCA preenche por dedução (só se vier do doc)
_FISCAL_FIELDS = {"NCM", "CFOP", "CEST"}


def _sugerir_fiscal(
    fcol: str, row: dict, *, fiscal_rag, desc_col_value: str,
    ncm_sugerido_codigo: str | None = None,
) -> tuple[str, str | None]:
    """Monta uma sugestão TEXTUAL pra pendência de NCM/CEST — nunca escreve
    na célula (a guarda-fiscal continua vazia; isso só enriquece o motivo
    em `rep.pending` pra acelerar a auditoria humana). Ordem de tentativa:
    histórico já auditado da própria empresa (`fiscal_rag`, se fornecida)
    primeiro — acerta mais quando a empresa já classificou produto
    parecido; tabela oficial (ncm_lookup.py/cest_lookup.py) como
    fallback — funciona mesmo pra produto totalmente novo. Sem
    correspondência forte o suficiente em nenhuma fonte, devolve string
    vazia — a pendência fica sem sugestão, nunca com um palpite fraco.

    Devolve (texto_da_sugestao, codigo_ncm_usado) — o segundo elemento
    permite que a pendência de CEST reaproveite o MESMO NCM que acabou de
    ser sugerido pra este produto, em vez de buscar de novo por conta
    própria (evitando sugerir NCM diferentes pro mesmo produto em campos
    diferentes da mesma linha)."""
    if fcol == "CFOP" or not desc_col_value:
        return "", None  # CFOP não tem tabela de referência ligada ainda

    if fcol == "NCM":
        if fiscal_rag is not None:
            sugestoes = fiscal_rag.query(desc_col_value, field_type="ncm")
            if sugestoes:
                s = sugestoes[0]
                texto = f'NCM {s.value} (confiança {s.confidence:.2f}, histórico: "{s.matched_description[:40]}")'
                return texto, s.value
        from phoenix_kernel.documents.ncm_lookup import search_ncm_by_text
        resultados = search_ncm_by_text(desc_col_value, limit=1)
        if resultados:
            entry, score = resultados[0]
            texto = f'NCM {entry.codigo_formatado} (score {score:.2f}, tabela oficial: "{entry.descricao[:40]}")'
            return texto, entry.codigo
        return "", None

    if fcol == "CEST":
        if fiscal_rag is not None:
            sugestoes = fiscal_rag.query(desc_col_value, field_type="cest")
            if sugestoes:
                s = sugestoes[0]
                return f'CEST {s.value} (confiança {s.confidence:.2f}, histórico: "{s.matched_description[:40]}")', None
        from phoenix_kernel.documents.ncm_lookup import search_ncm_by_text
        from phoenix_kernel.documents.cest_lookup import get_cest_for_ncm
        # prioridade: NCM já preenchido na linha > NCM já sugerido pra esse
        # mesmo produto (evita inconsistência) > busca nova por conta própria
        ncm_atual = _ci_get(row, "NCM")
        if ncm_atual and not _empty(ncm_atual):
            candidato_ncm = ncm_atual
        elif ncm_sugerido_codigo:
            candidato_ncm = ncm_sugerido_codigo
        else:
            resultados = search_ncm_by_text(desc_col_value, limit=1)
            candidato_ncm = resultados[0][0].codigo if resultados else None
        if candidato_ncm:
            cests = get_cest_for_ncm(candidato_ncm, apenas_especifico=True) or get_cest_for_ncm(candidato_ncm)
            if cests:
                c = cests[0]
                return f'CEST {c.cest} (via NCM {candidato_ncm}, tabela oficial: "{c.descricao[:40]}")', None
        return "", None
    return "", None


# ---------------------------------------------------------------------------
# camada 1 — regras de derivação (declarativas)
# ---------------------------------------------------------------------------

@dataclass
class DerivationRule:
    """Preenche `target` a partir de outra coluna, de um default dominante, ou
    de um gerador sequencial. Só age quando `target` está vazio."""
    target: str
    copy_from: Optional[str] = None          # copia o valor de outra coluna
    default: Optional[str] = None            # valor fixo (ex.: "NACIONAL")
    sequential_prefix: Optional[str] = None  # gera "PROD001", "PROD002"...
    sequential_numeric: bool = False         # gera "4369", "4370"...


def _build_default_rules() -> list[DerivationRule]:
    """As regras que usei ao terminar os catálogos MarketUP à mão. Genéricas o
    suficiente para qualquer catálogo com esse layout; colunas ausentes são
    simplesmente ignoradas."""
    return [
        DerivationRule(target="Origem", default="NACIONAL"),
        DerivationRule(target="Tipo", default="Mercadoria para Revenda"),
        DerivationRule(target="Categoria PDV", copy_from="Categoria na Loja Virtual"),
        DerivationRule(target="Botão PDV", copy_from="Categoria na Loja Virtual"),
        DerivationRule(target="Subcategoria na Loja Virtual", copy_from="Subcategoria do Produto"),
        DerivationRule(target="Categoria na Loja Virtual", copy_from="Categoria do Produto"),
        DerivationRule(target="Código Interno", sequential_prefix="PROD"),
        DerivationRule(target="Código Balança", sequential_numeric=True),
    ]


# ---------------------------------------------------------------------------
# camada 2 — geração de conteúdo por categoria
# ---------------------------------------------------------------------------

# vocabulário de tags por categoria (minúsculo, dedup). Personalizado por
# produto com marca + tamanho. Extensível sem tocar no código do motor.
_TAG_VOCAB: dict[str, list[str]] = {
    # construção
    "argamassas": ["argamassa", "assentamento", "revestimento", "obra", "reforma"],
    "tintas": ["tinta", "pintura", "acabamento", "parede", "decoração"],
    "hidráulica": ["hidráulica", "encanamento", "conexão", "água", "instalação"],
    "desempenadeiras": ["desempenadeira", "aço", "reboco", "nivelamento", "acabamento"],
    "pincéis / trinchas": ["pincel", "trincha", "pintura", "aplicação", "acabamento"],
    "massas corridas": ["massa corrida", "parede", "nivelamento", "preparação"],
    "fitas": ["fita", "adesiva", "vedação", "fixação"],
    "luvas de proteção": ["luva", "proteção", "epi", "segurança"],
    # conveniência
    "bebidas": ["bebida", "conveniência", "gelado", "refrescante"],
    "destilados": ["destilado", "drink", "premium", "coquetel"],
    "tabacaria": ["tabacaria", "cigarro", "fumo"],
    "petiscos": ["petisco", "aperitivo", "tira-gosto"],
    "queijos": ["queijo", "frios", "gourmet", "tábua"],
}


def _generate_tags(desc, marca, categoria) -> str:
    cat = str(categoria or "").lower().strip()
    base = list(_TAG_VOCAB.get(cat, []))
    if not base:
        # sem vocabulário da categoria: usa a própria categoria como semente
        base = [w for w in re.split(r"[\s/]+", cat) if len(w) > 2][:3]
    tags = list(base)
    if marca and not _empty(marca):
        tags.append(str(marca).lower())
    size = _size_token(desc)
    if size:
        tags.append(size.lower())
    seen: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.append(t)
    return ", ".join(seen[:12])


def _generate_specs(row: dict) -> str:
    desc = str(row.get("Descrição", "") or "")
    parts = []
    marca = row.get("Marca")
    if marca and not _empty(marca):
        parts.append(f"Marca: {marca}")
    size = _size_token(desc)
    if size:
        parts.append(f"Conteúdo/Medida: {size}")
    cat = _ci_get(row, "Categoria do Produto")
    if cat and not _empty(cat):
        parts.append(f"Categoria: {cat}")
    dims = []
    for eixo, coln in [("A", "Altura (cm)"), ("L", "Largura (cm)"), ("P", "Profundidade (cm)")]:
        v = row.get(coln)
        if v and str(v) not in ("0", "0.0", ""):
            dims.append(f"{eixo} {v}cm")
    if dims:
        parts.append("Dimensões: " + " x ".join(dims))
    peso = row.get("Peso (Kg)")
    if peso and str(peso) not in ("0", "0.0", ""):
        parts.append(f"Peso: {peso} kg")
    low = desc.lower()
    if "inox" in low:
        parts.append("Material: Aço inox")
    elif "aço" in low:
        parts.append("Material: Aço")
    elif "pvc" in low:
        parts.append("Material: PVC")
    parts.append("Indicação: Uso profissional e residencial")
    return " | ".join(parts)


def _generate_included_items(row: dict) -> str:
    desc = str(_ci_get(row, "Descrição") or "")
    low = desc.lower()
    if "combo" in low or "kit" in low:
        m = re.search(r"kit\s+(\d+)", low)
        return f"{m.group(1)} unidades" if m else "Itens do kit conforme descrição"
    size = _size_token(desc)
    return f"1 unidade ({size})" if size else "1 unidade"


def _generate_sales_trigger(row: dict, desc: str) -> str:
    """Passo 3 (colaboração "cross-sell/gatilhos"): gera um parágrafo
    persuasivo determinístico para a coluna "Descrição do Produto" (o campo
    de marketing/loja online, que ficava vazio na maioria dos produtos).

    Se `row["_quadrant_context"]` estiver presente (o chamador — normalmente
    o resident, usando cross_sell_suggester.match_product_to_quadrant — já
    casou este produto com um quadrante de margem capturado nos Passos 1/2),
    o TOM muda: produto do quadrante ÂNCORA (menor margem, isca) ganha um
    gatilho de preço/oportunidade; produto de quadrante COMPLEMENTAR (margem
    maior) ganha um gatilho de qualidade/experiência — a mesma lógica que a
    estratégia original descreveu, agora escrita produto a produto.

    Sem contexto de quadrante (documento sem essa estratégia, ou produto sem
    match), cai num template genérico a partir do nome — nunca fica vazio.
    Determinístico: funciona sem LLM. Quando `llm_rewrite` está disponível
    (ver smart_fill_rows), o texto gerado aqui é só o PONTO DE PARTIDA — o
    LLM pode reescrever com mais fluência, usando o mesmo contexto."""
    nome = _name_core(desc) or desc.strip()
    if not nome:
        return ""

    ctx = row.get("_quadrant_context") or {}
    papel = ctx.get("role_hint", "")
    margem_label = ctx.get("margin_label", "")
    quadrante_nome = ctx.get("quadrant_name", "")

    if papel == "ancora":
        return (
            f"<p><b>{nome}</b> é a nossa oferta de entrada — "
            f"{margem_label.lower() if margem_label else 'preço que atrai'}, "
            f"o motivo pra você vir até a loja hoje.</p>"
        )
    if papel == "complementar":
        return (
            f"<p><b>{nome}</b> eleva sua experiência — "
            f"{margem_label.lower() if margem_label else 'a escolha de quem quer mais qualidade'}"
            + (f" (linha {quadrante_nome})" if quadrante_nome else "")
            + ".</p>"
        )

    categoria = _ci_get(row, "Categoria do Produto") or ""
    return f"<p><b>{nome}</b>{' — ' + categoria if categoria else ''}, pronto para sua loja.</p>"


# ---------------------------------------------------------------------------
# motor
# ---------------------------------------------------------------------------

def smart_fill_rows(
    rows: list[dict],
    *,
    rules: Optional[list[DerivationRule]] = None,
    generate_content: bool = True,
    seq_state: Optional[dict] = None,
    llm_rewrite: Optional[Callable[[str, dict], str]] = None,
    fiscal_rag=None,
) -> tuple[list[dict], FillReport]:
    """Preenche in-place os campos vazios de cada linha, raciocinando por
    camadas. Devolve (rows, relatório). Não sobrescreve nada já preenchido.

    `seq_state`: dict com o último número usado por prefixo sequencial, para
    continuar séries já existentes na planilha (ex.: {"PROD": 568, "_bal": 4368}).
    Se None, a função descobre o máximo existente nas próprias linhas.

    `fiscal_rag` (opcional, ver fiscal_rag.FiscalRAG): quando NCM/CEST vem
    vazio, a guarda-fiscal SEMPRE deixa o campo em branco (nunca inventa —
    ver `_FISCAL_FIELDS` abaixo) — mas se uma FiscalRAG (histórico já
    auditado da empresa) for passada, ou como fallback a tabela oficial
    (ncm_lookup.py/cest_lookup.py), a PENDÊNCIA registrada em `rep.pending`
    ganha uma sugestão com fonte e confiança, pra acelerar a auditoria
    humana sem nunca decidir sozinha.

    `llm_rewrite(field_type, row)`: callback opcional para reescrever o
    conteúdo gerado com mais fluência (o determinístico é sempre o fallback).
    """
    rules = rules or _build_default_rules()
    report = FillReport()

    # descobre o estado das séries sequenciais a partir do que já existe
    if seq_state is None:
        seq_state = {}
    for rule in rules:
        if rule.sequential_prefix and rule.sequential_prefix not in seq_state:
            mx = 0
            for row in rows:
                v = str(row.get(rule.target, "") or "")
                m = re.match(re.escape(rule.sequential_prefix) + r"(\d+)", v)
                if m:
                    mx = max(mx, int(m.group(1)))
            seq_state[rule.sequential_prefix] = mx
        if rule.sequential_numeric and rule.target not in seq_state:
            mx = 0
            for row in rows:
                v = str(row.get(rule.target, "") or "")
                if v.isdigit():
                    mx = max(mx, int(v))
            seq_state[rule.target] = mx

    for row_idx, row in enumerate(rows):
        desc = _ci_get(row, "Descrição") or ""
        placeholder = _is_placeholder_name(desc)

        # --- camada 1: derivação ---
        for rule in rules:
            if rule.target not in row:
                continue  # coluna não existe neste template
            if not _empty(row.get(rule.target)):
                continue
            value = None
            if rule.copy_from and not _empty(row.get(rule.copy_from)):
                value = row[rule.copy_from]
            elif rule.default is not None:
                value = rule.default
            elif rule.sequential_prefix:
                seq_state[rule.sequential_prefix] += 1
                value = f"{rule.sequential_prefix}{seq_state[rule.sequential_prefix]:03d}"
            elif rule.sequential_numeric:
                seq_state[rule.target] += 1
                value = str(seq_state[rule.target])
            if value is not None:
                row[rule.target] = value
                report._bump(report.filled_by_rule, rule.target)

        # --- guarda-fiscal: nunca deduz NCM/CFOP/CEST ---
        # NCM primeiro (não em qualquer ordem — _FISCAL_FIELDS é um set):
        # o CEST reaproveita a MESMA sugestão de NCM já encontrada pra este
        # produto, em vez de buscar de novo por conta própria e arriscar
        # sugerir um NCM diferente daquele que apareceu na própria
        # pendência de NCM logo acima (inconsistência real encontrada e
        # corrigida ainda em teste, antes de qualquer entrega).
        ncm_sugerido_codigo = None
        for fcol in ("NCM", "CFOP", "CEST"):
            if fcol not in row or not _empty(row.get(fcol)):
                continue
            report._bump(report.left_blank_fiscal, fcol)
            motivo = "campo fiscal — exige classificação real, não deduzido"
            sugestao, codigo_ncm_usado = _sugerir_fiscal(
                fcol, row, fiscal_rag=fiscal_rag, desc_col_value=desc,
                ncm_sugerido_codigo=ncm_sugerido_codigo,
            )
            if fcol == "NCM" and codigo_ncm_usado:
                ncm_sugerido_codigo = codigo_ncm_usado
            if sugestao:
                motivo = f"{motivo} | sugestão: {sugestao}"
            report.pending.append((desc, fcol, motivo, row_idx))

        # --- produto-fantasma: não gera conteúdo pra nome genérico ---
        if placeholder:
            report.left_blank_placeholder += 1
            report.pending.append((desc, "Descrição", "produto genérico sem nome real — precisa do nome", row_idx))
            continue

        # --- camada 2: geração de conteúdo ---
        if generate_content:
            gens = {
                "Tags": lambda: _generate_tags(desc, _ci_get(row, "Marca"), _ci_get(row, "Categoria do Produto")),
                "Especificações": lambda: _generate_specs(row),
                "Itens Inclusos": lambda: _generate_included_items(row),
                "Modelo": lambda: _name_core(desc)[:60],
                # PHX-NEW (Passo 3, "gatilho de venda"): gera um parágrafo
                # persuasivo determinístico para "Descrição do Produto" — o
                # campo de marketing da loja online. Se o produto foi casado
                # com um quadrante de estratégia (Passos 1/2, via
                # row["_quadrant_context"], preenchido pelo chamador ANTES
                # de rodar o smart_filler), o tom muda: âncora (isca) ganha
                # gatilho de preço/oportunidade; complementar ganha gatilho
                # de qualidade/experiência. Sem contexto, cai num template
                # genérico — nunca fica vazio, nunca trava sem LLM.
                "Descrição do Produto": lambda: _generate_sales_trigger(row, desc),
            }
            for col_name, gen in gens.items():
                actual_key = _ci_find_key(row, col_name)
                if actual_key and _empty(row.get(actual_key)):
                    value = gen()
                    if value and llm_rewrite:
                        try:
                            value = llm_rewrite(col_name, row) or value
                        except Exception:
                            pass  # fallback determinístico
                    if value:
                        row[actual_key] = value
                        report._bump(report.filled_by_generation, actual_key)

    return rows, report


def smart_fill_xlsx(
    input_path: str,
    output_path: str,
    *,
    sheet_name: Optional[str] = None,
    rules: Optional[list[DerivationRule]] = None,
    generate_content: bool = True,
    seq_state: Optional[dict] = None,
    llm_rewrite: Optional[Callable[[str, dict], str]] = None,
    row_enricher: Optional[Callable[[dict], None]] = None,
    fiscal_rag=None,
) -> FillReport:
    """Aplica o smart fill a uma planilha .xlsx REAL, célula a célula,
    preservando tudo que já existe (formatação, fórmulas, outras abas, e todo
    valor não-vazio). Escreve um arquivo NOVO em `output_path` — nunca
    sobrescreve o de entrada. Devolve o relatório (o que foi preenchido por
    regra, o que foi gerado, o que ficou em branco de propósito e por quê).

    `row_enricher(row)`: callback opcional (Passo 3, "gatilho de venda")
    chamado em cada linha ANTES da geração de conteúdo, para adicionar
    contexto extra que não vem do próprio Excel (ex.: casar o produto com um
    quadrante de estratégia comercial capturado em outro documento — ver
    cross_sell_suggester.py). Modifica `row` in-place; não afeta o que é
    escrito na planilha além do que os geradores de conteúdo usarem dele.

    Reusa a mesma lógica de `smart_fill_rows`: lê a linha como dict
    {header: valor}, raciocina, e grava de volta só as células que estavam
    vazias e ganharam valor."""
    import openpyxl

    wb = openpyxl.load_workbook(input_path)  # sem data_only: preserva fórmulas
    ws = wb[sheet_name] if sheet_name else wb.active
    headers = [c.value for c in ws[1]]
    col_index = {h: j + 1 for j, h in enumerate(headers) if h}

    # planilha -> lista de dicts
    rows: list[dict] = []
    for r in range(2, ws.max_row + 1):
        rows.append({h: ws.cell(r, col_index[h]).value for h in col_index})

    if row_enricher:
        for row in rows:
            row_enricher(row)

    # snapshot do que estava vazio, para escrever SÓ o que mudou
    was_empty = [{h: _empty(row.get(h)) for h in col_index} for row in rows]

    rows, report = smart_fill_rows(
        rows, rules=rules, generate_content=generate_content,
        seq_state=seq_state, llm_rewrite=llm_rewrite, fiscal_rag=fiscal_rag,
    )

    # grava de volta só as células que estavam vazias e agora têm valor
    for i, row in enumerate(rows):
        r = i + 2
        for h in col_index:
            if was_empty[i][h] and not _empty(row.get(h)):
                ws.cell(r, col_index[h]).value = row[h]

    # PHX-NEW (2026-09-06, achado real do usuário): antes, `report.pending`
    # era calculado certinho (sugestão de NCM/CEST vindo da tabela oficial
    # ou do histórico da empresa) mas nunca chegava a lugar nenhum visível
    # no arquivo entregue - só a CONTAGEM sobrevivia até a resposta da API.
    # Agora cada pendência vira uma linha na aba _PHOENIX_AUDIT (mesma aba,
    # mesmo formato que o pipeline determinístico mais novo já usa pra
    # conflitos de marca/preço/dimensão - reaproveitado, não duplicado).
    if report.pending:
        if _AUDIT_SHEET_NAME in wb.sheetnames:
            audit_ws = wb[_AUDIT_SHEET_NAME]
        else:
            audit_ws = wb.create_sheet(_AUDIT_SHEET_NAME)
            audit_ws.append(_AUDIT_HEADERS)
        for desc, fcol, motivo, row_idx in report.pending:
            spreadsheet_row = row_idx + 2  # mesma conversão de índice usada acima (cabeçalho ocupa a linha 1)
            audit_ws.append(
                AuditRow(
                    canonical_id=f"smart_fill_r{spreadsheet_row}",
                    row_number=spreadsheet_row,
                    column_header=fcol,
                    field_type="fiscal_pending" if fcol in ("NCM", "CFOP", "CEST") else "content_pending",
                    status="sugestao_disponivel" if "sugestão:" in motivo else "sem_sugestao",
                    alternatives=motivo,
                    source_record_ids=desc,
                ).as_row()
            )

    wb.save(output_path)
    return report
