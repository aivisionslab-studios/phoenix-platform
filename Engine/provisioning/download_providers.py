import urllib.request
import urllib.error
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# PHX-FIX (auditoria completa): sem timeout, um download de modelo de
# imagem/áudio (GBs) que trava no meio (rede caiu, servidor parou de
# responder) fica pendurado pra sempre - o bug original do flux1-schnell
# "corrompido" no início desta auditoria é compatível com exatamente
# isso (download nunca terminou de verdade, mas nada acusou erro).
_DOWNLOAD_TIMEOUT_SEC = 120  # por leitura de socket, não pro arquivo inteiro

class BaseProvider:
    @staticmethod
    def download(provider_data: dict, target_path) -> tuple[bool, str | None]:
        raise NotImplementedError

class HttpProvider(BaseProvider):
    @staticmethod
    def download(provider_data: dict, target_path) -> tuple[bool, str | None]:
        """Baixa 'url' pra 'target_path'. Devolve (sucesso, motivo) - o
        motivo é None em caso de sucesso e uma mensagem legível em caso de
        falha (PHX-FIX, auditoria 2026-08-20, Seção 14: antes devolvia só
        um bool, e qualquer HTTPError (401 autenticação exigida, 404 link
        morto, 5xx erro do servidor) virava o mesmo "Erro -> ..." genérico
        no log, sem chegar structured até quem chama get_asset() -
        catalog/assets/flux_vae.json e a "SDXL VAE Fix" de
        install/common.ps1 estouravam exatamente 401/404 e o usuário só via
        'falha ao baixar', sem saber se era link morto, autenticação
        exigida, ou rede fora do ar - três problemas com soluções bem
        diferentes)."""
        url = provider_data.get("url")
        if not url:
            return False, "provider_data sem 'url'."

        target_path = Path(target_path)
        # PHX-FIX: baixa pra um .part e só renomeia pro nome final se
        # completar - assim um download interrompido nunca deixa um
        # arquivo "válido" (mesmo nome final, tamanho errado) que o
        # AssetManager trataria como cache reutilizável na próxima vez.
        part_path = target_path.with_name(target_path.name + ".part")

        req = urllib.request.Request(url, headers={"User-Agent": "Phoenix-Engine-AssetManager/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_SEC) as response, open(part_path, "wb") as out:
                # PHX-FIX (2026-08-23, achado real durante o teste do
                # auto-download do Kokoro: um download de verdade contra o
                # GitHub, nesta mesma sessão, terminou o loop abaixo sem
                # nenhuma exceção mas gravou só 64739264 de 325532387 bytes
                # esperados - a conexão parece ter caído no meio e
                # response.read() simplesmente voltou a devolver b"" mais
                # cedo, sem erro. Sem essa checagem, esse .part virava o
                # arquivo "final" (>0 bytes, sem exceção) e o AssetManager
                # tratava como cache válido pra sempre - exatamente a mesma
                # classe de bug já documentada aqui (o flux1-schnell
                # "corrompido"), só que causada por EOF prematuro em vez de
                # HTTP error. Content-Length nem sempre vem no header (alguns
                # servidores usam chunked/streaming) - por isso só valida
                # quando o servidor de fato informa o tamanho esperado.
                # getattr (não response.headers direto): testes existentes
                # mockam urlopen com um double simples (io.BytesIO) sem
                # atributo 'headers' - resposta real do urllib sempre tem,
                # mas esta checagem não pode quebrar quem usa um double sem
                # isso (comportamento vira "não valida", igual antes desta
                # correção, em vez de estourar AttributeError).
                response_headers = getattr(response, "headers", None)
                expected_size_raw = response_headers.get("Content-Length") if response_headers is not None else None
                expected_size = int(expected_size_raw) if expected_size_raw and str(expected_size_raw).isdigit() else None
                bytes_written = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    bytes_written += len(chunk)

            if not part_path.exists() or part_path.stat().st_size == 0:
                logger.error(f"HttpProvider: download resultou em arquivo vazio -> {url}")
                part_path.unlink(missing_ok=True)
                return False, f"Download completou mas o arquivo ficou vazio (url: {url})."

            if expected_size is not None and bytes_written != expected_size:
                logger.error(
                    f"HttpProvider: download incompleto -> {url} "
                    f"(recebeu {bytes_written} de {expected_size} bytes esperados)"
                )
                part_path.unlink(missing_ok=True)
                return False, (
                    f"Download interrompido no meio (recebeu {bytes_written} de {expected_size} bytes "
                    f"esperados) ao baixar {url} - provavelmente a conexão caiu. Tente novamente."
                )

            part_path.replace(target_path)
            return True, None
        except urllib.error.HTTPError as e:
            part_path.unlink(missing_ok=True)
            if e.code in (401, 403):
                reason = (
                    f"HTTP {e.code} (não autorizado) ao baixar {url} - o link provavelmente "
                    "exige login/licença aceita no Hugging Face (repo 'gated'); download "
                    "automático sem token não funciona aqui. Baixe manualmente, autenticado, "
                    "e coloque o arquivo no destino esperado."
                )
            elif e.code == 404:
                reason = (
                    f"HTTP 404 (não encontrado) ao baixar {url} - o link está morto ou o nome "
                    "do arquivo mudou no repositório remoto. Este catálogo precisa ser corrigido "
                    "(URL/nome de arquivo errado) ou removido."
                )
            else:
                reason = f"HTTP {e.code} ({e.reason}) ao baixar {url}."
            logger.error(f"HttpProvider: {reason}")
            return False, reason
        except Exception as e:
            part_path.unlink(missing_ok=True)
            reason = f"Erro ao baixar {url}: {e}"
            logger.error(f"HttpProvider: {reason}")
            return False, reason

class ProviderFactory:
    @staticmethod
    def get_provider(provider_name: str) -> BaseProvider:
        if provider_name == "http": return HttpProvider()
        raise ValueError(f"Provedor desconhecido: {provider_name}")
