---
memory_type: intrinsic
scope: permanent
loaded_by: ResidentManager (referência de como consultar as próprias memórias)
---

# Arquitetura de memória da Phoenix (quatro camadas)

Este diretório (`phoenix_memory/`) implementa a separação de
responsabilidades definida para a Phoenix 5.0. Cada camada tem um
papel diferente — não misturar conteúdo entre elas.

| Camada | Pasta | Papel | Muda com que frequência |
|---|---|---|---|
| Intrínseca | `intrinsic/` | Identidade, missão, regras de decisão | Quase nunca |
| Procedural | `procedures/` | "Receitas de bolo" — o passo a passo de tarefas conhecidas | Quando se descobre um fluxo novo/melhor |
| Engenharia (RAG) | `rag/` | Detalhes técnicos: flags, erros conhecidos, scripts, comandos exatos | Frequentemente, conforme mais testes são feitos |
| Máquina (Experiência) | `machine/` | Fatos aprendidos sobre ESTA máquina específica: benchmarks, o que funciona, o que trava | A cada novo teste/experimento |

## Fluxo de consulta recomendado

```
Usuário pede algo
      ↓
ResidentManager carrega intrinsic/ (sempre)
      ↓
Detecta a intenção (ex: "rodar Flux", "transcrever vídeo")
      ↓
Carrega o procedures/*.md relevante (o "como fazer")
      ↓
Consulta machine/*.json (o que já sabemos sobre ESTA máquina
  para essa tarefa — evita repetir testes que já falharam)
      ↓
Consulta rag/* apenas para o detalhe fino que falta
  (uma flag exata, um erro específico, um script)
      ↓
Se ainda faltar algo → busca na web
      ↓
Monta a Mission, mostra o plano, aguarda aprovação
      ↓
Services Engine executa (nunca o LLM gera comando de shell direto)
      ↓
Resultado é registrado de volta em machine/*.json
  (a Phoenix aprende com cada execução)
```

## Regra de ouro
- `intrinsic/` responde "quem eu sou e como devo pensar".
- `procedures/` responde "como eu faço isso, passo a passo".
- `rag/` responde "qual é o detalhe técnico exato disso".
- `machine/` responde "o que já aconteceu quando eu tentei isso antes,
  nesta máquina específica".

Nunca colocar uma receita procedural inteira dentro do RAG (isso o
transforma em um depósito de tudo). Nunca colocar fatos de experiência
de máquina dentro de `intrinsic/` (isso muda rápido demais e não é
identidade permanente).
