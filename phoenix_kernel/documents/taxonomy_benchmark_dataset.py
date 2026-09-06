"""Phoenix Document Pipeline V2 - montagem do dataset do benchmark
semântico REAL (grupo `taxonomy_resolver.py`) a partir do `Produtos.xlsx`
de verdade da loja (MarketUP), pedido explícito do usuário depois do A/B
`--no-think` nos 5 cenários fixos.

NÃO chama nenhum LLM - é só extração + amostragem estratificada
determinística do XLSX real, isolado de tudo mais (nenhum arquivo do
pipeline ou dos arquivos protegidos da feature de planilha é tocado ou
importado aqui). O resultado é um CSV que `taxonomy_benchmark_run.py`
consome depois de rodar contra o Qwen real.

RODADA A (esta primeira entrega) - taxonomia da LOJA VIRTUAL
(`Categoria na Loja Virtual`/`Subcategoria na Loja Virtual`), por decisão
explícita do usuário: essa taxonomia está mais limpa/consistente que a do
ERP (`Categoria do Produto`/`Subcategoria do Produto`), então vira o
primeiro benchmark semântico "de referência confiável". A RODADA B (ERP)
fica pra depois, de propósito, porque aquela taxonomia tem inconsistência
histórica de grafia (`Destilados`/`DESTILADOS`, `COMBOS`/`COMBOS/ KITS`,
`Refrigerante`/`Refrigerantes`) que precisa de normalização conservadora
(trim + case-insensitive + espaços duplicados, SEM fundir valores
semanticamente diferentes) e vira um teste de robustez a taxonomia
bagunçada, não só de acerto do modelo - fora do escopo desta entrega.

MAPEAMENTO DE COLUNAS (real, pedido explícito do usuário - "não precisa
CSV manual, use o Produtos.xlsx diretamente"):
    explicit_product_name      <- "Nome na Loja Virtual"
    brand                      <- "Marca"
    tags                       <- "Tags"
    description_html           <- "Descrição do Produto"
    expected_store_category    <- "Categoria na Loja Virtual"
    expected_store_subcategory <- "Subcategoria na Loja Virtual"

A taxonomia (allowlist de categoria + allowlist de subcategoria POR
categoria) é construída DIRETO dos valores distintos reais dessas duas
colunas, preservando a relação pai->filho - nunca hardcoded/inventada.
Nenhuma normalização é aplicada nesta rodada (a taxonomia da loja já
veio limpa na inspeção manual - sem duplicata de maiúscula/minúscula).

REFERENCE_STATUS / REFERENCE_QUALITY (pedido explícito do usuário - "não
quero que ausência de gabarito ou gabarito suspeito vire erro do
modelo"):
  - reference_status="ok"      -> produto tem categoria E subcategoria
    da loja preenchidas no XLSX real; entra na métrica principal de
    acerto.
  - reference_status="missing" -> uma ou as duas estão vazias no XLSX
    real (9 produtos no total, incluindo 3 das 4 variantes de Batata
    Pringles - nenhuma norma da loja foi inventada pra elas). Fica FORA
    da métrica principal de acerto; o interessante aqui é observar o que
    o Qwen escolhe e com que confidence, não se "acertou".
  - reference_quality="suspect" -> reservado pra um gabarito
    presente mas internamente inconsistente com o resto da planilha
    (ex.: o caso já encontrado no ERP, Coca-Cola Plus Café Espresso,
    onde `Categoria do Produto` = "Refrigerantes" ao invés de "BEBIDAS" -
    mas na taxonomia da LOJA esse mesmo produto está correto
    ("Bebidas" -> "Refrigerantes"), então ele entra aqui como "ok", não
    "suspect" - a marca "suspect" é sobre ESTA taxonomia, não a outra).
    Nesta amostra da loja, o único caso que anotamos como digno de nota
    (mas sem classificar como "suspect", ver AMBIGUITY_NOTES abaixo) é
    a variante "Paprika" de Pringles, a ÚNICA das 4 com categoria da loja
    preenchida - e ela caiu em "Conveniência" -> "Utilidades Rápidas",
    uma colocação defensável mas não óbvia pra um salgadinho (as outras
    3 variantes de Pringles nem têm categoria da loja nenhuma). Isso é
    uma escolha humana debatível, não um erro mecânico óbvio como o caso
    do ERP - por isso vira ambiguity_level="high" com uma nota, não
    reference_quality="suspect" (esse rótulo fica reservado pra
    inconsistência estrutural clara, não pra "eu acho estranho").

AMBIGUITY_LEVEL - definido por INSPEÇÃO HUMANA (deste script + revisão
do usuário), ANTES de rodar qualquer coisa contra o Qwen (pedido
explícito: "não usar o Qwen pra definir a própria dificuldade do
teste"). Critério explícito (do usuário):
    low    -> nome/tags praticamente entregam a categoria sozinhos.
    medium -> precisa juntar 2+ sinais, mas há uma resposta dominante.
    high   -> duas+ categorias são defensáveis, OU o produto não encaixa
              bem na taxonomia (inclui TODOS os reference_status=missing
              por definição - se nem o humano soube classificar, o caso
              é genuinamente difícil).
As atribuições ficam na coluna `ambiguity_level` do CSV de saída, com uma
`ambiguity_note` curta explicando o raciocínio - revise/sobrescreva à
vontade antes de rodar o benchmark.

AMOSTRAGEM: estratificada por `Categoria na Loja Virtual`, com pelo menos
uma linha de cada subcategoria real quando possível, mais um conjunto
CURADO de casos deliberadamente difíceis/interessantes (as 3 variantes de
Pringles sem categoria de loja, a variante Paprika com a colocação
debatível, mais alguns outros produtos "Frios" sem categoria e a bebida
alcoólica classificada como "Destilados" no ERP mas sem par na loja) -
pedido explícito do usuário pra não deixar o benchmark "bonito demais, só
de cerveja óbvia". Seed fixa (--seed, default 42) pra reprodutibilidade.
"""
from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

_NAME_COL = "Nome na Loja Virtual"
_BRAND_COL = "Marca"
_TAGS_COL = "Tags"
_DESC_COL = "Descrição do Produto"
_STORE_CAT_COL = "Categoria na Loja Virtual"
_STORE_SUBCAT_COL = "Subcategoria na Loja Virtual"

# Curadoria explícita (pedido do usuário) - índices de linha do XLSX
# (0-based, mesma indexação do pandas) escolhidos à mão por serem
# genuinamente difíceis ou reveladores, não escolhidos aleatoriamente.
# Reavaliar se o XLSX real mudar de linha/ordem.
_CURATED_ROW_NOTES: dict[int, tuple[str, str]] = {
    # (ambiguity_level, ambiguity_note)
    4: ("high", "sem categoria/subcategoria de loja no XLSX real - 1 de 4 variantes de Pringles; ERP diz CONVENIÊNCIA->Diversos, mas isso não é a taxonomia da loja"),
    377: ("high", "sem categoria/subcategoria de loja no XLSX real - outra variante de Pringles sem par na loja"),
    453: ("high", "sem categoria/subcategoria de loja no XLSX real - outra variante de Pringles sem par na loja"),
    456: ("high", "ÚNICA variante de Pringles com categoria de loja preenchida (Conveniência->Utilidades Rápidas) - essa subcategoria parece ser um balde geral de 'compra rápida' (o mesmo XLSX também põe barra de chocolate Lindt ali), então a colocação em si é defensável; o genuinamente estranho é a INCONSISTÊNCIA - as outras 3 variantes de Pringles idênticas em tudo, menos o sabor, não têm categoria de loja nenhuma. Vale ver se o Qwen classifica as 4 variantes de forma coerente entre si"),
    470: ("high", "sem categoria/subcategoria de loja no XLSX real; ERP classifica como Destilados->Vodka (bebida pronta com vodka) - fronteira genuína entre 'bebida pronta' e 'destilado'"),
    355: ("high", "sem categoria/subcategoria de loja no XLSX real - item de frios (Salame), a taxonomia da loja não parece ter uma casa clara pra frios"),
    363: ("high", "sem categoria/subcategoria de loja no XLSX real, e também sem categoria ERP - nem o humano soube classificar dentro desta taxonomia"),
}


@dataclass
class _DatasetRow:
    row_id: int
    explicit_product_name: str
    brand: str
    tags: str
    description_html: str
    expected_store_category: Optional[str]
    expected_store_subcategory: Optional[str]
    reference_status: str  # "ok" | "missing"
    reference_quality: str  # "ok" | "suspect"
    ambiguity_level: str  # "low" | "medium" | "high" - revisar antes de rodar
    ambiguity_note: str


def load_products(xlsx_path: str) -> pd.DataFrame:
    return pd.read_excel(xlsx_path, sheet_name="Plan 1")


def build_store_taxonomy(df: pd.DataFrame) -> dict:
    """Constrói a allowlist de categoria + subcategoria-por-categoria
    DIRETO dos valores distintos reais do XLSX, preservando pai->filho -
    nunca hardcoded. Ignora pares com categoria ou subcategoria vazia."""
    valid = df[df[_STORE_CAT_COL].notna() & df[_STORE_SUBCAT_COL].notna()]
    categories = sorted(valid[_STORE_CAT_COL].unique().tolist())
    subcats_by_category: dict[str, list[str]] = {}
    for cat in categories:
        subs = sorted(valid[valid[_STORE_CAT_COL] == cat][_STORE_SUBCAT_COL].unique().tolist())
        subcats_by_category[cat] = subs
    return {"categories": categories, "subcategories_by_category": subcats_by_category}


def _classify_ambiguity_low_medium(row: pd.Series) -> tuple[str, str]:
    """Heurística SIMPLES e conservadora pra pré-marcar low/medium nos
    casos SEM problema de referência (a maioria da amostra) - só marca
    "low" quando a categoria aparece quase literalmente no nome, senão
    marca "medium" por padrão. Revisão humana (o usuário) tem a palavra
    final - isso é só um ponto de partida honesto, não uma decisão
    automática escondida."""
    name = str(row[_NAME_COL] or "").lower()
    subcat = str(row[_STORE_SUBCAT_COL] or "").lower()
    obvious_tokens = {
        "cervejas": ["cerveja"], "refrigerantes": ["refrigerante", "coca-cola", "guaraná", "soda"],
        "energéticos": ["energético", "energetico"], "águas": ["água", "agua"],
        "vinhos e espumantes": ["espumante", "champagne"], "sucos": ["suco"],
        "chás": ["chá", "cha "], "bebidas prontas": [],
        "vodka": ["vodka"], "cachaça": ["cachaça", "cachaca"], "gin": ["gin"],
        "whisky": ["whisky", "whiskey"], "rum": ["rum"], "tequila": ["tequila"],
        "licor": ["licor"], "aperitivos": ["aperitivo"],
        "salgadinhos": ["salgadinho"], "snacks": ["snack"], "amendoins": ["amendoim"], "batata chips": ["batata"],
        "cigarros": ["cigarro"], "charutos": ["charuto"],
        "gelo": ["gelo"], "utilidades rápidas": [],
        "vinhos tintos": ["tinto"], "vinhos brancos": ["branco"], "vinhos rosé": ["rosé", "rose"],
        "combos cerveja": ["cerveja"], "combos festa": [], "combos premium": [],
    }
    tokens = obvious_tokens.get(subcat, [])
    if tokens and any(t in name for t in tokens):
        return "low", "nome do produto menciona a subcategoria quase literalmente"
    return "medium", "categoria plausível pelo tipo de produto, mas exige juntar nome+marca+tags, não é literal no nome"


def select_sample(df: pd.DataFrame, *, seed: int = 42, per_category_target: Optional[dict] = None) -> list[_DatasetRow]:
    per_category_target = per_category_target or {
        "Bebidas": 11, "Destilados": 6, "Petiscos": 4, "Tabacaria": 2,
        "Conveniência": 2, "Vinhos e Espumantes": 2, "Combos/ Kits": 2,
    }
    rng = random.Random(seed)
    rows: list[_DatasetRow] = []
    used_idx: set[int] = set()

    valid = df[df[_STORE_CAT_COL].notna() & df[_STORE_SUBCAT_COL].notna()]

    for category, target in per_category_target.items():
        cat_df = valid[valid[_STORE_CAT_COL] == category]
        if cat_df.empty:
            continue
        subcats = sorted(cat_df[_STORE_SUBCAT_COL].unique().tolist())
        picked_idx: list[int] = []
        # primeiro, tenta 1 linha de cada subcategoria distinta (cobertura)
        for sub in subcats:
            if len(picked_idx) >= target:
                break
            candidates = cat_df[cat_df[_STORE_SUBCAT_COL] == sub].index.tolist()
            candidates = [i for i in candidates if i not in used_idx]
            if candidates:
                choice = rng.choice(candidates)
                picked_idx.append(choice)
                used_idx.add(choice)
        # completa o alvo com amostra aleatória (seed fixa) dentro da categoria
        remaining_pool = [i for i in cat_df.index.tolist() if i not in used_idx]
        rng.shuffle(remaining_pool)
        while len(picked_idx) < target and remaining_pool:
            choice = remaining_pool.pop()
            picked_idx.append(choice)
            used_idx.add(choice)

        for idx in picked_idx:
            r = df.loc[idx]
            level, note = _classify_ambiguity_low_medium(r)
            rows.append(_DatasetRow(
                row_id=int(idx),
                explicit_product_name=str(r[_NAME_COL] or ""),
                brand=str(r[_BRAND_COL]) if pd.notna(r[_BRAND_COL]) else "",
                tags=str(r[_TAGS_COL]) if pd.notna(r[_TAGS_COL]) else "",
                description_html=str(r[_DESC_COL]) if pd.notna(r[_DESC_COL]) else "",
                expected_store_category=str(r[_STORE_CAT_COL]),
                expected_store_subcategory=str(r[_STORE_SUBCAT_COL]),
                reference_status="ok",
                reference_quality="ok",
                ambiguity_level=level,
                ambiguity_note=note,
            ))

    # casos curados (deliberadamente difíceis/reveladores) - adicionados
    # por cima da amostra estratificada, não substituem nada dela.
    for idx, (level, note) in _CURATED_ROW_NOTES.items():
        if idx in used_idx or idx not in df.index:
            continue
        r = df.loc[idx]
        has_cat = pd.notna(r[_STORE_CAT_COL]) and pd.notna(r[_STORE_SUBCAT_COL])
        rows.append(_DatasetRow(
            row_id=int(idx),
            explicit_product_name=str(r[_NAME_COL] or ""),
            brand=str(r[_BRAND_COL]) if pd.notna(r[_BRAND_COL]) else "",
            tags=str(r[_TAGS_COL]) if pd.notna(r[_TAGS_COL]) else "",
            description_html=str(r[_DESC_COL]) if pd.notna(r[_DESC_COL]) else "",
            expected_store_category=str(r[_STORE_CAT_COL]) if has_cat else None,
            expected_store_subcategory=str(r[_STORE_SUBCAT_COL]) if has_cat else None,
            reference_status="ok" if has_cat else "missing",
            reference_quality="ok",
            ambiguity_level=level,
            ambiguity_note=note,
        ))
        used_idx.add(idx)

    return rows


_CSV_FIELDS = [
    "row_id", "explicit_product_name", "brand", "tags", "description_html",
    "expected_store_category", "expected_store_subcategory",
    "reference_status", "reference_quality", "ambiguity_level", "ambiguity_note",
]


def write_dataset_csv(rows: list[_DatasetRow], out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "row_id": row.row_id,
                "explicit_product_name": row.explicit_product_name,
                "brand": row.brand,
                "tags": row.tags,
                "description_html": row.description_html,
                "expected_store_category": row.expected_store_category or "",
                "expected_store_subcategory": row.expected_store_subcategory or "",
                "reference_status": row.reference_status,
                "reference_quality": row.reference_quality,
                "ambiguity_level": row.ambiguity_level,
                "ambiguity_note": row.ambiguity_note,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx-path", required=True)
    parser.add_argument("--out-csv", default="taxonomy_benchmark_store_dataset.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = load_products(args.xlsx_path)
    taxonomy = build_store_taxonomy(df)
    print("Categorias reais (Loja Virtual):", taxonomy["categories"])
    for cat, subs in taxonomy["subcategories_by_category"].items():
        print(f"  {cat} -> {subs}")

    rows = select_sample(df, seed=args.seed)
    write_dataset_csv(rows, args.out_csv)
    print(f"\n{len(rows)} produtos selecionados -> {args.out_csv}")
    by_status = {}
    for r in rows:
        by_status[r.reference_status] = by_status.get(r.reference_status, 0) + 1
    print("por reference_status:", by_status)


if __name__ == "__main__":
    main()
