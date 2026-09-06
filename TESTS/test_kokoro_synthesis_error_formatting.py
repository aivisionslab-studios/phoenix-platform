"""
Teste de regressão pra um bug real achado nesta sessão (2026-08-23), ao
testar o modo GPU (v49, onnxruntime-directml) na máquina real do usuário:
TODOS os blocos de um audiolivro falharam na síntese, e o log mostrado pra
ele foi:

    Bloco 0 falhou na síntese ('utf-8' codec can't decode byte 0xe2 in
    position 376: invalid continuation byte) - pulado, resto do documento
    continua.

Isso parecia um problema de texto/codificação do documento, mas NÃO era -
o terminal bruto do Phoenix Engine mostrava o erro real logo acima:
onnxruntime::ExecuteKernel falhando no nó ConvTranspose do vocoder do
Kokoro rodando em DmlExecutionProvider (GPU via DirectML), com uma
mensagem nativa do Windows ("Parâmetro incorreto", HRESULT 80070057) que
veio acentuada numa codepage não-UTF-8. A conversão pybind11 dessa
mensagem de C++ pra Python falhou com UnicodeDecodeError - e essa exceção
SECUNDÁRIA (não a original do onnxruntime) foi o que efetivamente chegou
até o `except Exception as e` do nosso código, mascarando completamente a
causa raiz real (incompatibilidade do Kokoro com DirectML nesta GPU).

describe_synthesis_error() (phoenix_kernel/runtime/drivers/kokoro_tts.py)
reconhece esse padrão especificamente e aponta o usuário na direção certa
(conferir o terminal, considerar voltar pra CPU) em vez de deixar a
mensagem de "codec" confusa e sem contexto. Para qualquer outro tipo de
exceção, se comporta exatamente como str(e) - nenhuma mudança de
comportamento fora do caso específico.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_kernel.runtime.drivers.kokoro_tts import describe_synthesis_error


def _make_real_unicode_decode_error(byte_position_message: str = "byte 0xe2 in position 376: invalid continuation byte") -> UnicodeDecodeError:
    # Reproduz o formato REAL do erro visto no log do usuário (não um
    # UnicodeDecodeError genérico) - decodificando de propósito um byte
    # inválido em UTF-8, igual ao que a conversão pybind11 fez de verdade.
    try:
        b"\xe2\x28\xa1".decode("utf-8")
    except UnicodeDecodeError as e:
        return e
    raise AssertionError("esperava que o decode de propósito falhasse")


def test_unicode_decode_error_gets_actionable_dml_explanation():
    e = _make_real_unicode_decode_error()
    msg = describe_synthesis_error(e)

    assert "onnxruntime" in msg.lower()
    assert "windows" in msg.lower()
    assert "diretml".lower() in msg.lower() or "directml" in msg.lower()
    assert "cpu" in msg.lower(), "precisa sugerir voltar pra CPU como próximo passo prático"
    # A mensagem original do UnicodeDecodeError continua presente (não
    # esconde o erro técnico, só ACRESCENTA contexto) - alguém que já sabe
    # o que está acontecendo ainda consegue conferir o detalhe original.
    assert "0xe2" in msg or "invalid continuation byte" in msg


def test_normal_exception_passes_through_unchanged():
    # Nenhuma mudança de comportamento pra qualquer outra exceção comum -
    # describe_synthesis_error não pode inventar contexto pra erros que não
    # têm nada a ver com o bug do DirectML.
    e = RuntimeError("modelo Kokoro não encontrado no disco")
    assert describe_synthesis_error(e) == str(e)


def test_value_error_passes_through_unchanged():
    e = ValueError("idioma 'xx' não suportado")
    assert describe_synthesis_error(e) == str(e)


def test_never_raises_even_if_str_itself_fails():
    # Rede de segurança: um handler de erro que quebra ao tentar DESCREVER
    # outro erro seria pior que o problema original (um crash escondendo o
    # crash). Simula uma exceção cujo __str__ propositalmente falha.
    class _PathologicalError(Exception):
        def __str__(self):
            raise RuntimeError("__str__ também quebrado")

    msg = describe_synthesis_error(_PathologicalError())
    assert "PathologicalError" in msg or "não foi possível obter detalhes" in msg
