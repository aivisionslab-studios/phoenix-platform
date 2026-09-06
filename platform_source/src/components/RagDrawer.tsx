import React, { useEffect, useRef, useState } from 'react';
import { RagDocument } from '../types';
import { Database, X, Upload, Trash2, FileText, Search, Plus, ShieldCheck, ShieldAlert } from 'lucide-react';

interface RagLimitsState {
  plan: string;
  current_documents: number;
  max_documents: number | null;
  max_upload_mb: number;
  max_characters: number;
  current_characters: number;
  repository_security?: { integrity_valid: boolean; reason?: string };
}

interface RagDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  documents: RagDocument[];
  onAddDocument: (title: string, content: string, type: 'PDF' | 'MD' | 'CODE' | 'TXT') => Promise<void>;
  onAddFile: (file: File) => Promise<void>;
  onDeleteDocument: (id: string) => Promise<void>;
}

export const RagDrawer: React.FC<RagDrawerProps> = ({
  isOpen,
  onClose,
  documents,
  onAddDocument,
  onAddFile,
  onDeleteDocument
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [selectedType, setSelectedType] = useState<'MD' | 'PDF' | 'CODE' | 'TXT'>('MD');
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [limits, setLimits] = useState<RagLimitsState | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // PHX-NEW (2026-09-06, achado real do usuário + análise técnica detalhada
  // trazida por ele: "phoenix nao diz estado atual do RAG de usuario e
  // deveria dizer ou direcionar usuario a entender contexto: 25mb ou 10/10
  // ou 500 mil caracteres"): a rota /api/rag/limits já existia e já
  // devolvia praticamente tudo isso (plano, documentos atual/máximo, MB
  // máximo, caracteres máximo, integridade) - só nunca era consumida por
  // nenhuma tela. Busca ao abrir o drawer e depois de cada ação que muda
  // a contagem (add/delete), pra nunca mostrar um número desatualizado.
  const refreshLimits = async () => {
    try {
      const res = await fetch('/api/rag/limits');
      if (!res.ok) return;
      const data = await res.json();
      if (data?.ok) {
        setLimits({
          plan: data.plan,
          current_documents: data.current_documents,
          max_documents: data.max_documents,
          max_upload_mb: data.max_upload_mb,
          max_characters: data.max_characters,
          current_characters: data.current_characters,
          repository_security: data.repository_security,
        });
      }
    } catch {
      // estado de limites é informativo - uma falha aqui não deve impedir
      // o resto do drawer de funcionar (upload/busca continuam operando
      // normalmente mesmo sem o painel de estado).
    }
  };

  useEffect(() => {
    if (isOpen) refreshLimits();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen) return null;

  const filteredDocs = documents.filter(d => 
    d.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleManualAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim() || isSubmitting) return;
    setIsSubmitting(true);
    setAddError(null);
    try {
      await onAddDocument(newTitle.trim(), newContent.trim(), selectedType);
      setNewTitle('');
      setNewContent('');
      await refreshLimits();
    } catch (err: any) {
      // PHX-FIX (2026-09-06, mesmo achado do usuário): antes, um erro
      // lançado por onAddDocument (ex.: limite de caracteres/documentos
      // excedido, agora com mensagem específica desde a correção do
      // status 422 no backend) propagava sem tratamento nenhum aqui -
      // nunca chegava a aparecer pro usuário, só um erro silencioso no
      // console do navegador.
      setAddError(err?.message || 'Falha ao indexar documento.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const uploadFile = async (file: File) => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setAddError(null);
    try {
      await onAddFile(file);
      await refreshLimits();
    } catch (err: any) {
      setAddError(err?.message || 'Falha ao indexar arquivo.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await uploadFile(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-xs transition-opacity animate-fadeIn">
      <div className="w-full max-w-xl bg-[#101317] border-l border-[#262d35] h-full flex flex-col shadow-2xl overflow-hidden">
        
        {/* Drawer Header */}
        <div className="px-6 py-4 border-b border-[#262d35] bg-[#14181d] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded bg-[#37d67a]/20 border border-[#37d67a] flex items-center justify-center text-[#37d67a]">
              <Database className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white tracking-widest uppercase font-display">
                RAG KNOWLEDGE REPOSITORY
              </h2>
              <p className="text-[11px] text-[#8d98a5] font-mono">
                Port 8000 · Embeddings locais · Similaridade cosseno
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded text-[#8d98a5] hover:text-white hover:bg-[#262d35] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drawer Content */}
        <div className="p-6 overflow-y-auto space-y-6 flex-grow">

          {/* PHX-NEW (2026-09-06): estado explícito do plano - antes o
              usuário só descobria "10/10" ou "500 mil caracteres" quando
              um upload já tinha falhado, e precisava adivinhar qual dos
              três limites (documentos/MB/caracteres) foi o culpado.

              PHX-FIX (2026-09-06, correção conceitual do usuário, com
              análise técnica detalhada): "Texto por doc." mostrando só
              "150M car." comunicava um teto POR ARQUIVO - a regra real é
              um orçamento AGREGADO do repositório inteiro (os 10
              documentos, juntos, compartilham 150M caracteres). Trocado
              por "CONHECIMENTO INDEXADO" com uso atual/limite, percentual
              e barra de progresso - o usuário entende de imediato que é
              capacidade total do repositório, não de cada arquivo. */}
          {limits && (
            <div className="bg-[#0b0d10] border border-[#262d35] rounded-lg p-3.5 space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div>
                  <p className="text-[10px] text-[#8d98a5] uppercase font-mono tracking-wider">Plano</p>
                  <p className="text-xs font-bold text-white font-mono uppercase">{limits.plan}</p>
                </div>
                <div>
                  <p className="text-[10px] text-[#8d98a5] uppercase font-mono tracking-wider">Documentos</p>
                  <p className={`text-xs font-bold font-mono ${limits.max_documents != null && limits.current_documents >= limits.max_documents ? 'text-[#ff334b]' : 'text-white'}`}>
                    {limits.current_documents} / {limits.max_documents ?? '∞'}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-[#8d98a5] uppercase font-mono tracking-wider">Máx. por arquivo</p>
                  <p className="text-xs font-bold text-white font-mono">{limits.max_upload_mb} MB</p>
                </div>
              </div>

              <div className="pt-2 border-t border-[#262d35]">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-[10px] text-[#8d98a5] uppercase font-mono tracking-wider">Conhecimento indexado (total do repositório)</p>
                  <p className="text-[10px] text-[#8d98a5] font-mono">
                    {limits.max_characters > 0 ? ((limits.current_characters / limits.max_characters) * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) : 0}% utilizado
                  </p>
                </div>
                <p className="text-xs font-bold text-white font-mono mb-1.5">
                  {limits.current_characters.toLocaleString('pt-BR')} / {limits.max_characters.toLocaleString('pt-BR')} caracteres
                </p>
                <div className="w-full h-1.5 bg-[#14181d] rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${limits.current_characters / limits.max_characters > 0.9 ? 'bg-[#ff334b]' : limits.current_characters / limits.max_characters > 0.7 ? 'bg-yellow-500' : 'bg-[#37d67a]'}`}
                    style={{ width: `${Math.min(100, (limits.current_characters / limits.max_characters) * 100)}%` }}
                  />
                </div>
                <p className="text-[10px] text-[#8d98a5] font-mono mt-1">
                  Disponível: {Math.max(0, limits.max_characters - limits.current_characters).toLocaleString('pt-BR')} caracteres
                </p>
              </div>

              {limits.repository_security && (
                <div className="flex items-center gap-1.5 pt-1 border-t border-[#262d35]">
                  {limits.repository_security.integrity_valid ? (
                    <>
                      <ShieldCheck className="w-3.5 h-3.5 text-[#37d67a]" />
                      <span className="text-[10px] text-[#37d67a] font-mono uppercase">Integridade OK</span>
                    </>
                  ) : (
                    <>
                      <ShieldAlert className="w-3.5 h-3.5 text-[#ff334b]" />
                      <span className="text-[10px] text-[#ff334b] font-mono uppercase">
                        RAG bloqueado por integridade{limits.repository_security.reason ? ` — ${limits.repository_security.reason}` : ''}
                      </span>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* PHX-NEW (2026-09-06): erro específico do último upload/adição
              manual - antes um limite excedido (ou qualquer outra falha)
              nunca chegava a aparecer nesta tela, só um erro silencioso no
              console do navegador (ver handleManualAdd/uploadFile acima). */}
          {addError && (
            <div className="bg-[#ff334b]/10 border border-[#ff334b]/40 rounded-lg p-3 flex items-start gap-2">
              <ShieldAlert className="w-4 h-4 text-[#ff334b] flex-shrink-0 mt-0.5" />
              <p className="text-xs text-[#ff334b] font-mono">{addError}</p>
            </div>
          )}
          
          {/* Drag & Drop Upload Zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-6 text-center transition-all ${
              isDragging
                ? 'border-[#ff334b] bg-[#ff334b]/10'
                : 'border-[#262d35] bg-[#0b0d10] hover:border-[#3a4450]'
            }`}
          >
            <Upload className="w-8 h-8 mx-auto text-[#8d98a5] mb-2" />
            <h3 className="text-xs font-bold text-white uppercase tracking-wider font-mono">
              Drag & Drop Hardware Manuals or Specs
            </h3>
            <p className="text-[11px] text-[#8d98a5] font-mono mt-1">
              Supports .PDF, .DOCX, .XLSX, .PPTX, .TXT, .MD, and images (.PNG/.JPG/.WEBP — read via vision OCR)
            </p>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              disabled={isSubmitting}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (file) await uploadFile(file);
                e.target.value = '';
              }}
            />
          </div>

          {/* Quick Manual Add Form */}
          <form onSubmit={handleManualAdd} className="bg-[#0b0d10] border border-[#262d35] rounded-lg p-4 space-y-3">
            <span className="text-xs font-bold text-white uppercase tracking-wider font-mono block">
              Quick Index Document
            </span>
            <div className="flex gap-2">
              <input
                type="text"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="e.g. polaris_vulkan_pipeline_opt.md"
                className="flex-grow bg-[#14181d] border border-[#262d35] rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-[#37d67a]"
              />
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value as any)}
                className="bg-[#14181d] border border-[#262d35] rounded px-2.5 py-2 text-xs font-mono text-white focus:outline-none focus:border-[#37d67a]"
              >
                <option value="MD">.MD</option>
                <option value="PDF">.PDF</option>
                <option value="CODE">.CODE</option>
                <option value="TXT">.TXT</option>
              </select>
              <button
                type="submit"
                disabled={isSubmitting || !newTitle.trim() || !newContent.trim()}
                className="px-3.5 py-2 bg-[#37d67a] hover:bg-[#2fc26d] text-black font-bold text-xs uppercase font-mono rounded transition-all flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Index</span>
              </button>
            </div>
            <textarea
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              placeholder="Cole aqui o conteúdo real que será indexado no RAG..."
              rows={5}
              className="w-full resize-y bg-[#14181d] border border-[#262d35] rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-[#37d67a]"
            />
          </form>

          {/* Search Bar & Document List */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-white uppercase tracking-wider font-mono">
                Indexed Documents ({filteredDocs.length})
              </span>
              
              <div className="relative w-48">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-[#8d98a5]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter docs..."
                  className="w-full bg-[#0b0d10] border border-[#262d35] rounded pl-8 pr-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-[#37d67a]"
                />
              </div>
            </div>

            <div className="space-y-2">
              {filteredDocs.map((doc) => (
                <div
                  key={doc.id}
                  className="p-3 bg-[#0b0d10] border border-[#262d35] rounded-lg flex items-center justify-between hover:border-[#3a4450] transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-7 h-7 rounded bg-[#14181d] border border-[#262d35] flex items-center justify-center text-[#37d67a]">
                      <FileText className="w-3.5 h-3.5" />
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-white font-mono">{doc.title}</h4>
                      <div className="flex items-center gap-2 text-[10px] text-[#8d98a5] font-mono mt-0.5">
                        <span>{doc.sizeKb} KB</span>
                        <span>•</span>
                        <span>{doc.chunks} Chunks</span>
                        <span>•</span>
                        <span className="text-[#37d67a]">{doc.status}</span>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={async () => { await onDeleteDocument(doc.id); await refreshLimits(); }}
                    className="p-1.5 text-[#8d98a5] hover:text-[#ff334b] hover:bg-[#ff334b]/10 rounded transition-colors"
                    title="Remove from vector index"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[#262d35] bg-[#14181d] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-white text-black font-bold text-xs uppercase font-mono hover:bg-[#e7e7e7] transition-all"
          >
            Close Repository
          </button>
        </div>

      </div>
    </div>
  );
};
