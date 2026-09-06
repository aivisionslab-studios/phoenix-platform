import React, { useEffect, useMemo, useState } from 'react';
import { Check, Copy, Cpu, Download, FileText, HardDrive, Shield, X } from 'lucide-react';

interface SystemReportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface SystemReport {
  generated_at: string;
  status: string;
  engine: { name: string; version: string; uptime_seconds: number; python: string };
  hardware: { cpu?: string; ram_mb?: number; gpu?: string; vram_mb?: number; backends?: string[] };
  environment: Array<{ name: string; available: boolean }>;
  storage: { workspace: string; total_bytes?: number; used_bytes?: number; free_bytes?: number; error?: string };
  rag: { document_count: number; plan: string; max_documents: number | null; max_upload_bytes: number; max_characters: number };
  ahde: { available: boolean; health_score: number | null; health_status: string };
  license: { project: string; third_party_components: string };
}

const formatBytes = (value?: number) => {
  if (typeof value !== 'number') return 'não informado';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(unit >= 3 ? 1 : 0)} ${units[unit]}`;
};

const Row = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="flex justify-between gap-4 py-1 border-b border-[#14141c] last:border-0">
    <span className="text-[#6f7884]">{label}</span>
    <span className="text-white text-right break-all">{value}</span>
  </div>
);

export const SystemReportModal: React.FC<SystemReportModalProps> = ({ isOpen, onClose }) => {
  const [report, setReport] = useState<SystemReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [viewJson, setViewJson] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch('/api/system/report')
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
        return body as SystemReport;
      })
      .then((body) => { if (!cancelled) setReport(body); })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isOpen]);

  const json = useMemo(() => JSON.stringify(report, null, 2), [report]);

  if (!isOpen) return null;

  const copyReport = async () => {
    if (!report) return;
    await navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadReport = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `phoenix-system-report-${report.generated_at.slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm">
      <div className="w-full max-w-3xl bg-[#0d0d12] border border-[#252532] rounded-lg max-h-[90vh] overflow-hidden flex flex-col text-[#e0e0e0] font-mono">
        <div className="px-6 py-4 border-b border-[#252532] flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold tracking-[0.16em] uppercase text-white">Phoenix // relatório do sistema</h2>
            <p className="text-xs text-[#6f7884] mt-1">Dados coletados agora pelo Phoenix Engine; ausências não são estimadas.</p>
          </div>
          <button onClick={onClose} className="p-1.5 text-[#6f7884] hover:text-white" title="Fechar"><X className="w-5 h-5" /></button>
        </div>

        <div className="px-6 py-2.5 border-b border-[#252532] flex items-center justify-between gap-3">
          <span className={error ? 'text-[#ff6175]' : report ? 'text-[#37d67a]' : 'text-[#8d98a5]'}>
            {loading ? 'COLETANDO…' : error ? 'INDISPONÍVEL' : report ? 'RELATÓRIO RECEBIDO' : 'AGUARDANDO'}
          </span>
          <div className="flex gap-3 text-[11px]">
            <button disabled={!report} onClick={() => setViewJson(!viewJson)} className="text-[#4fa3ff] disabled:opacity-40 flex gap-1"><FileText className="w-3 h-3" />{viewJson ? 'Visual' : 'JSON'}</button>
            <button disabled={!report} onClick={copyReport} className="text-[#37d67a] disabled:opacity-40 flex gap-1">{copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}{copied ? 'Copiado' : 'Copiar'}</button>
            <button disabled={!report} onClick={downloadReport} className="text-[#8d98a5] disabled:opacity-40 flex gap-1"><Download className="w-3 h-3" />Baixar</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 text-xs">
          {error && <div className="p-4 border border-[#ff334b]/50 bg-[#ff334b]/10 text-[#ff8b9a]">{error}</div>}
          {loading && !report && <div className="text-[#8d98a5]">Consultando a porta 8000…</div>}
          {report && viewJson && <pre className="p-4 bg-[#050508] border border-[#252532] rounded text-[#4fa3ff] overflow-x-auto">{json}</pre>}
          {report && !viewJson && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <section className="p-4 bg-[#09090e] border border-[#252532] rounded">
                  <h3 className="uppercase text-[#4fa3ff] mb-3 flex gap-2"><Cpu className="w-4 h-4" />Hardware detectado</h3>
                  <Row label="CPU" value={report.hardware.cpu || 'não informado'} />
                  <Row label="RAM" value={report.hardware.ram_mb ? `${report.hardware.ram_mb} MB` : 'não informado'} />
                  <Row label="GPU" value={report.hardware.gpu || 'não informado'} />
                  <Row label="VRAM" value={report.hardware.vram_mb ? `${report.hardware.vram_mb} MB` : 'não informado'} />
                  <Row label="Backends" value={(report.hardware.backends || []).join(', ') || 'nenhum informado'} />
                </section>
                <section className="p-4 bg-[#09090e] border border-[#252532] rounded">
                  <h3 className="uppercase text-[#37d67a] mb-3 flex gap-2"><Shield className="w-4 h-4" />Ambiente verificado</h3>
                  {report.environment.map((item) => <Row key={item.name} label={item.name} value={item.available ? 'disponível' : 'não detectado'} />)}
                </section>
              </div>
              <section className="p-4 bg-[#09090e] border border-[#252532] rounded">
                <h3 className="uppercase text-[#f59e0b] mb-3 flex gap-2"><HardDrive className="w-4 h-4" />Armazenamento e RAG</h3>
                <Row label="Workspace" value={report.storage.workspace} />
                <Row label="Espaço livre" value={report.storage.error || formatBytes(report.storage.free_bytes)} />
                <Row label="Documentos lógicos" value={report.rag.document_count} />
                <Row label="Plano / limite" value={`${report.rag.plan} / ${report.rag.max_documents ?? 'sem limite numérico'}`} />
                <Row label="Máximo por arquivo" value={formatBytes(report.rag.max_upload_bytes)} />
              </section>
              <section className="p-4 bg-[#09090e] border border-[#252532] rounded text-[#8d98a5]">
                <Row label="AHDE" value={report.ahde.available ? 'disponível' : 'indisponível'} />
                <Row label="Saúde AHDE" value={report.ahde.health_status === 'not_calculated' ? 'não calculada' : String(report.ahde.health_score)} />
                <Row label="Licença do projeto" value={report.license.project} />
                <p className="mt-3">{report.license.third_party_components}</p>
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
