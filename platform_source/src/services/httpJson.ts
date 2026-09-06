/**
 * src/services/httpJson.ts
 *
 * PHX-NEW (auditoria 2026-08-20, "Frontend JSON error handling" / Seção 11):
 * achado real do usuário - anexar áudio no chat Aviary e mandar produzia
 * `Unexpected token '<', "<!DOCTYPE "... is not valid JSON` na tela. A causa
 * é sempre a mesma em todo o front: algum código chama `await response.json()`
 * sem checar o Content-Type antes, e quando o servidor devolve uma página de
 * erro HTML (proxy caiu na rota errada, Express devolveu o fallback do SPA,
 * corpo grande demais, 502 de um proxy reverso, etc.) o parser de JSON
 * quebra com uma mensagem ilegível pro usuário final.
 *
 * parseJsonResponse() centraliza a checagem: se o Content-Type não é
 * application/json, lê como texto e lança um erro claro e acionável em vez
 * de deixar o SyntaxError bruto do JSON.parse vazar pra UI.
 */

export class NonJsonResponseError extends Error {
  readonly contentType: string;
  readonly bodyPreview: string;
  readonly status: number;

  constructor(contentType: string, bodyPreview: string, status: number) {
    super(
      `Endpoint retornou conteúdo não-JSON (${contentType}). Início da resposta: ${bodyPreview}`
    );
    this.name = 'NonJsonResponseError';
    this.contentType = contentType;
    this.bodyPreview = bodyPreview;
    this.status = status;
  }
}

/**
 * Lê uma Response como JSON com segurança. Se o servidor devolveu algo que
 * não é JSON (tipicamente uma página HTML de erro), lança NonJsonResponseError
 * com uma mensagem clara em vez do SyntaxError bruto de `.json()`.
 */
export async function parseJsonResponse<T = any>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';

  if (!contentType.includes('application/json')) {
    const text = await response.text();
    throw new NonJsonResponseError(contentType || '(sem content-type)', text.slice(0, 120), response.status);
  }

  try {
    return (await response.json()) as T;
  } catch (e) {
    // Content-Type dizia JSON mas o corpo não parseou (corpo truncado, vazio, etc.)
    throw new NonJsonResponseError(contentType, '(falha ao fazer parse do corpo declarado como JSON)', response.status);
  }
}

/**
 * Mensagem amigável pra mostrar na UI quando parseJsonResponse falha,
 * dando uma dica de causa provável em vez de só repassar o erro técnico.
 */
export function describeNonJsonError(err: unknown): string {
  if (err instanceof NonJsonResponseError) {
    if (err.contentType.includes('text/html')) {
      return 'A rota esperada retornou HTML em vez de JSON. Verifique se o proxy/endpoint está ativo. ' + err.message;
    }
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}
