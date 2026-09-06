import React, { useState, useEffect } from 'react';
import { HardwareProfile, AhdeDevice, AhdeSensor, AhdeDiscoveryEvent, AhdeSnapshotData } from '../types';
import { 
  Cpu, X, Zap, Play, CheckCircle2, RefreshCw, BarChart2, ShieldCheck, 
  Thermometer, Activity, Database, Radio, Search, Filter, AlertTriangle, 
  HardDrive, Layers, Server, Gauge, Box, CpuIcon, Check, Copy
} from 'lucide-react';

interface HardwareDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  currentProfile: HardwareProfile;
  onSelectProfile: (profile: HardwareProfile) => void;
  onRunBenchmark: () => Promise<void>;
  isBenchmarking: boolean;
  benchmarkLog: string[];
  vulkanDetected: boolean | null;
}

export const HARDWARE_PRESETS: HardwareProfile[] = [
  {
    id: 'detected-hardware',
    name: 'Hardware detectado pelo Phoenix Engine',
    cpu: 'Aguardando descoberta',
    ram: 'Aguardando descoberta',
    ramTotalMB: 0,
    gpu: 'Aguardando descoberta',
    vram: 'Aguardando descoberta',
    vramTotalMB: 0,
    backend: 'Aguardando descoberta',
    driver: 'Não informado',
    gpuScore: 0,
    ramScore: 0,
    temperatureC: 0,
    fanSpeedPercent: 0
  }
];

export const HardwareDrawer: React.FC<HardwareDrawerProps> = ({
  isOpen,
  onClose,
  currentProfile,
  onRunBenchmark,
  isBenchmarking,
  benchmarkLog,
  vulkanDetected,
}) => {
  const [activeTab, setActiveTab] = useState<'sensors' | 'capabilities' | 'eventbus' | 'snapshot' | 'benchmark'>('sensors');
  const [sensorCategory, setSensorCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [devices, setDevices] = useState<AhdeDevice[]>([]);
  const [events, setEvents] = useState<AhdeDiscoveryEvent[]>([]);
  const [snapshot, setSnapshot] = useState<AhdeSnapshotData | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Poll AHDE sensors and events
  useEffect(() => {
    if (!isOpen) return;

    const fetchAhdeData = async () => {
      try {
        const [sensRes, evtRes, snapRes] = await Promise.all([
          fetch('/api/ahde/sensors'),
          fetch('/api/ahde/events'),
          fetch('/api/ahde/snapshot')
        ]);

        if (!sensRes.ok || !evtRes.ok || !snapRes.ok) {
          throw new Error(`Engine respondeu ${sensRes.status}/${evtRes.status}/${snapRes.status}`);
        }
        if (sensRes.ok) {
          const sensData = await sensRes.json();
          if (Array.isArray(sensData.devices)) {
            setDevices(sensData.devices);
          }
        }

        if (evtRes.ok) {
          const evtData = await evtRes.json();
          if (Array.isArray(evtData.events)) {
            setEvents(evtData.events);
          }
        }

        if (snapRes.ok) {
          const snapData = await snapRes.json();
          setSnapshot(snapData);
        }
        setLoadError(null);
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : 'AHDE indisponível');
      }
    };

    fetchAhdeData();
    const interval = setInterval(fetchAhdeData, 5000);
    return () => clearInterval(interval);
  }, [isOpen]);

  const handleTriggerScan = async () => {
    setIsScanning(true);
    try {
      const res = await fetch('/api/ahde/scan', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.devices) setDevices(data.devices);
        if (data.event) setEvents(prev => [data.event, ...prev]);
        setLoadError(null);
      } else {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      }
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Varredura AHDE falhou');
    }
    finally {
      setIsScanning(false);
    }
  };

  const handleCopySnapshot = () => {
    if (snapshot) {
      navigator.clipboard.writeText(JSON.stringify(snapshot, null, 2));
      setCopiedSnapshot(true);
      setTimeout(() => setCopiedSnapshot(false), 2000);
    }
  };

  if (!isOpen) return null;

  // Flatten and filter sensors
  const allSensors: AhdeSensor[] = devices.flatMap(d => d.sensors || []);
  const filteredSensors = allSensors.filter(sensor => {
    const matchesCategory = sensorCategory === 'all' || sensor.category === sensorCategory;
    const matchesSearch = searchQuery.trim() === '' || 
      sensor.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      sensor.device.toLowerCase().includes(searchQuery.toLowerCase()) ||
      sensor.type.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const getSensorColor = (sensor: AhdeSensor) => {
    if (sensor.type === 'Temperature') {
      const val = typeof sensor.value === 'number' ? sensor.value : 0;
      if (val > (sensor.criticalThreshold || 85)) return 'text-[#ff334b]';
      if (val > (sensor.warningThreshold || 75)) return 'text-[#f59e0b]';
      return 'text-[#37d67a]';
    }
    if (sensor.type === 'Load') {
      const val = typeof sensor.value === 'number' ? sensor.value : 0;
      if (val > (sensor.criticalThreshold || 90)) return 'text-[#ff334b]';
      if (val > (sensor.warningThreshold || 75)) return 'text-[#f59e0b]';
      return 'text-[#4fa3ff]';
    }
    return 'text-white';
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/75 backdrop-blur-xs transition-opacity animate-fadeIn select-none">
      <div className="w-full max-w-2xl bg-[#101317] border-l border-[#262d35] h-full flex flex-col shadow-2xl overflow-hidden text-[#e7e7e7]">
        
        {/* Header with AHDE Identity */}
        <div className="px-6 py-4 border-b border-[#262d35] bg-[#14181d] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded bg-[#ff334b]/20 border border-[#ff334b] flex items-center justify-center text-[#ff334b]">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-white tracking-widest uppercase font-display">
                  AHDE // HARDWARE DISCOVERY & SENSORS
                </h2>
                <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-[#37d67a]/20 border border-[#37d67a] text-[#37d67a]">
                  {loadError ? 'OFFLINE' : 'LIVE'}
                </span>
              </div>
              <p className="text-[11px] text-[#8d98a5] font-mono">
                Phoenix Hardware Engine • Machine: {snapshot?.machine_id || 'local'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleTriggerScan}
              disabled={isScanning}
              title="Rescan AHDE Sensors"
              className="p-1.5 rounded bg-[#1c2229] border border-[#262d35] text-[#8d98a5] hover:text-white hover:border-[#ff334b] transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${isScanning ? 'animate-spin text-[#ff334b]' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded text-[#8d98a5] hover:text-white hover:bg-[#262d35] transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-[#262d35] bg-[#0c0e11] px-4 overflow-x-auto">
          <button
            onClick={() => setActiveTab('sensors')}
            className={`px-4 py-2.5 text-xs font-mono font-bold uppercase tracking-wider flex items-center gap-1.5 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'sensors'
                ? 'border-[#ff334b] text-white bg-[#14181d]'
                : 'border-transparent text-[#8d98a5] hover:text-white'
            }`}
          >
            <Gauge className="w-3.5 h-3.5 text-[#ff334b]" />
            <span>Todos os Sensores ({allSensors.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('capabilities')}
            className={`px-4 py-2.5 text-xs font-mono font-bold uppercase tracking-wider flex items-center gap-1.5 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'capabilities'
                ? 'border-[#ff334b] text-white bg-[#14181d]'
                : 'border-transparent text-[#8d98a5] hover:text-white'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5 text-[#4fa3ff]" />
            <span>Capacidades & Perfis</span>
          </button>

          <button
            onClick={() => setActiveTab('eventbus')}
            className={`px-4 py-2.5 text-xs font-mono font-bold uppercase tracking-wider flex items-center gap-1.5 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'eventbus'
                ? 'border-[#ff334b] text-white bg-[#14181d]'
                : 'border-transparent text-[#8d98a5] hover:text-white'
            }`}
          >
            <Radio className="w-3.5 h-3.5 text-[#37d67a]" />
            <span>EventBus ({events.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('snapshot')}
            className={`px-4 py-2.5 text-xs font-mono font-bold uppercase tracking-wider flex items-center gap-1.5 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'snapshot'
                ? 'border-[#ff334b] text-white bg-[#14181d]'
                : 'border-transparent text-[#8d98a5] hover:text-white'
            }`}
          >
            <Database className="w-3.5 h-3.5 text-[#f59e0b]" />
            <span>Snapshot JSON</span>
          </button>

          <button
            onClick={() => setActiveTab('benchmark')}
            className={`px-4 py-2.5 text-xs font-mono font-bold uppercase tracking-wider flex items-center gap-1.5 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'benchmark'
                ? 'border-[#ff334b] text-white bg-[#14181d]'
                : 'border-transparent text-[#8d98a5] hover:text-white'
            }`}
          >
            <Zap className="w-3.5 h-3.5 text-[#ff334b]" />
            <span>Vulkan Bench</span>
          </button>
        </div>

        {loadError && (
          <div className="px-4 py-2 border-b border-[#ff334b]/40 bg-[#ff334b]/10 text-[11px] text-[#ff8b9a]">
            AHDE indisponível: {loadError}
          </div>
        )}

        {/* Drawer Content Body */}
        <div className="p-5 overflow-y-auto space-y-5 flex-grow font-mono">
          
          {/* TAB 1: ALL SENSORS */}
          {activeTab === 'sensors' && (
            <div className="space-y-4">
              
              {/* Filter and Search Bar */}
              <div className="flex flex-col sm:flex-row gap-2">
                <div className="relative flex-grow">
                  <Search className="w-4 h-4 text-[#8d98a5] absolute left-3 top-2.5" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Filtrar sensor (ex: temp, load, clock, vram, cpu)..."
                    className="w-full bg-[#0b0d10] border border-[#262d35] rounded pl-9 pr-3 py-1.5 text-xs text-white placeholder-[#5a6572] focus:outline-none focus:border-[#ff334b]"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2.5 top-2 text-[#8d98a5] hover:text-white"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                <div className="flex gap-1 overflow-x-auto pb-1">
                  {['all', 'cpu', 'gpu', 'memory', 'motherboard', 'storage'].map(cat => (
                    <button
                      key={cat}
                      onClick={() => setSensorCategory(cat)}
                      className={`px-2.5 py-1 text-[11px] font-bold rounded uppercase border transition-all ${
                        sensorCategory === cat
                          ? 'bg-[#ff334b] border-[#ff334b] text-white'
                          : 'bg-[#14181d] border-[#262d35] text-[#8d98a5] hover:text-white'
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
              </div>

              {/* Devices and Sensor List */}
              <div className="space-y-4">
                {devices
                  .filter(d => sensorCategory === 'all' || d.category === sensorCategory)
                  .map(device => {
                    const devSensors = (device.sensors || []).filter(s => {
                      return searchQuery.trim() === '' ||
                        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        s.type.toLowerCase().includes(searchQuery.toLowerCase());
                    });

                    if (devSensors.length === 0) return null;

                    return (
                      <div key={device.name} className="bg-[#0b0d10] border border-[#262d35] rounded-lg overflow-hidden">
                        {/* Device Header */}
                        <div className="px-4 py-2.5 bg-[#14181d] border-b border-[#262d35] flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {device.category === 'cpu' && <Cpu className="w-4 h-4 text-[#ff334b]" />}
                            {device.category === 'gpu' && <Zap className="w-4 h-4 text-[#ff334b]" />}
                            {device.category === 'memory' && <Layers className="w-4 h-4 text-[#4fa3ff]" />}
                            {device.category === 'motherboard' && <Server className="w-4 h-4 text-[#37d67a]" />}
                            {device.category === 'storage' && <HardDrive className="w-4 h-4 text-[#f59e0b]" />}
                            <span className="text-xs font-bold text-white tracking-wide">{device.name}</span>
                          </div>
                          <span className="text-[10px] text-[#8d98a5] uppercase">
                            {device.vendor || device.type} • {devSensors.length} sensores
                          </span>
                        </div>

                        {/* Sensor Grid */}
                        <div className="p-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {devSensors.map(sensor => {
                            const isNumeric = typeof sensor.value === 'number';
                            const numVal = isNumeric ? (sensor.value as number) : 0;
                            const maxVal = sensor.max || (sensor.type === 'Load' ? 100 : (sensor.type === 'Temperature' ? 100 : numVal * 1.5));
                            const pct = isNumeric && maxVal > 0 ? Math.min(100, Math.max(0, (numVal / maxVal) * 100)) : 0;

                            return (
                              <div key={sensor.id} className="p-2.5 rounded bg-[#101317] border border-[#1e232a] flex flex-col justify-between gap-1.5 hover:border-[#3a4450] transition-colors">
                                <div className="flex items-start justify-between gap-2">
                                  <span className="text-[11px] text-[#8d98a5] leading-tight line-clamp-1">{sensor.name}</span>
                                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#1c2229] text-[#8d98a5] border border-[#262d35] uppercase flex-shrink-0">
                                    {sensor.type}
                                  </span>
                                </div>

                                <div className="flex items-baseline justify-between">
                                  <span className={`text-sm font-bold ${getSensorColor(sensor)}`}>
                                    {sensor.value} {sensor.unit || ''}
                                  </span>
                                  {isNumeric && sensor.max && (
                                    <span className="text-[10px] text-[#5a6572]">
                                      max: {sensor.max} {sensor.unit || ''}
                                    </span>
                                  )}
                                </div>

                                {isNumeric && (sensor.type === 'Load' || sensor.type === 'Temperature') && (
                                  <div className="w-full h-1 bg-[#1a1f26] rounded-full overflow-hidden">
                                    <div 
                                      className={`h-full transition-all duration-500 ${
                                        pct > 80 ? 'bg-[#ff334b]' : pct > 60 ? 'bg-[#f59e0b]' : 'bg-[#37d67a]'
                                      }`}
                                      style={{ width: `${pct}%` }}
                                    />
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
              </div>

            </div>
          )}

          {/* TAB 2: CAPABILITY SNAPSHOT & PROFILES */}
          {activeTab === 'capabilities' && (
            <div className="space-y-5">
              {/* AHDE Capability Matrix (CapabilitySnapshot from contracts.py) */}
              <div className="bg-[#0b0d10] border border-[#262d35] rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between border-b border-[#1c2229] pb-2">
                  <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-[#37d67a]" />
                    AHDE CapabilitySnapshot (contracts.py)
                  </span>
                  <span className="text-[10px] text-[#8d98a5] font-bold">
                    {snapshot ? 'SNAPSHOT REAL' : 'AGUARDANDO SNAPSHOT'}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                  {Object.entries(snapshot?.capabilities || {}).map(([name, available]) => (
                    <div key={name} className="p-2.5 bg-[#14181d] rounded border border-[#262d35] flex items-center justify-between gap-2">
                      <span className="uppercase">{name}:</span>
                      <span className={`font-bold ${available ? 'text-[#37d67a]' : 'text-[#8d98a5]'}`}>
                        {available ? 'DETECTADO' : 'NÃO DETECTADO'}
                      </span>
                    </div>
                  ))}
                  {!snapshot && <span className="text-[#8d98a5]">Nenhuma capacidade recebida.</span>}
                </div>
              </div>

              {/* Hardware Profiles */}
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-white block mb-3">
                  Perfis de Hardware & Arquitetura
                </span>

                <div className="space-y-3">
                  {[currentProfile].map((preset) => {
                    const isActive = currentProfile.id === preset.id;
                    return (
                      <div
                        key={preset.id}
                        className={`p-4 rounded-lg border transition-all ${
                          isActive
                            ? 'bg-[#14181d] border-[#ff334b] shadow-[0_0_15px_rgba(255,51,75,0.2)]'
                            : 'bg-[#0b0d10] border-[#262d35] hover:border-[#3a4450]'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-bold text-white tracking-wide">{preset.name}</span>
                          {isActive && (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-[#ff334b] text-white">
                              DETECTADO
                            </span>
                          )}
                        </div>

                        <div className="grid grid-cols-2 gap-2 text-[11px] text-[#8d98a5]">
                          <div>CPU: <span className="text-white">{preset.cpu}</span></div>
                          <div>RAM: <span className="text-[#4fa3ff]">{preset.ram}</span></div>
                          <div>GPU: <span className="text-[#ff334b]">{preset.gpu}</span></div>
                          <div>VRAM: <span className="text-white">{preset.vram}</span></div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: EVENTBUS FEED (ChangeDetectionEngine fine events) */}
          {activeTab === 'eventbus' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b border-[#262d35] pb-2">
                <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                  <Radio className="w-4 h-4 text-[#37d67a] animate-pulse" />
                  Barramento Assíncrono AHDE (EventBus)
                </span>
                <span className="text-[10px] text-[#8d98a5]">
                  Filtro de ruído: ChangeDetectionEngine (1.0°C / 64MB)
                </span>
              </div>

              <div className="space-y-2">
                {events.length === 0 && (
                  <div className="p-3 text-xs text-[#8d98a5] border border-[#262d35] rounded-lg">
                    Nenhum evento AHDE capturado nesta sessão.
                  </div>
                )}
                {events.map((evt) => {
                  return (
                    <div key={evt.event_id} className="p-3 bg-[#0b0d10] border border-[#262d35] rounded-lg text-xs space-y-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`px-1.5 py-0.5 text-[9px] font-bold rounded ${
                            evt.priority === 'HIGH' ? 'bg-[#ff334b] text-white' : 'bg-[#1c2229] text-[#8d98a5] border border-[#262d35]'
                          }`}>
                            {evt.priority}
                          </span>
                          <span className="font-bold text-white">{evt.event_type}</span>
                        </div>
                        <span className="text-[10px] text-[#5a6572]">{new Date(evt.timestamp).toLocaleTimeString()}</span>
                      </div>

                      <div className="text-[11px] text-[#8d98a5] flex items-center gap-1">
                        <span>Origem:</span>
                        <span className="text-[#4fa3ff]">{evt.source}</span>
                        <span className="text-[#5a6572]">({evt.trace_id})</span>
                      </div>

                      <div className="p-2 rounded bg-[#14181d] border border-[#1c2229] text-[10px] text-[#37d67a] font-mono overflow-x-auto">
                        {JSON.stringify(evt.payload, null, 2)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* TAB 4: SNAPSHOT JSON */}
          {activeTab === 'snapshot' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b border-[#262d35] pb-2">
                <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                  <Database className="w-4 h-4 text-[#f59e0b]" />
                  HardwareSnapshot (contracts.py Schema v1.0)
                </span>
                
                <button
                  onClick={handleCopySnapshot}
                  className="px-2.5 py-1 rounded bg-[#1c2229] border border-[#262d35] text-xs text-[#8d98a5] hover:text-white flex items-center gap-1.5"
                >
                  {copiedSnapshot ? <Check className="w-3.5 h-3.5 text-[#37d67a]" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copiedSnapshot ? 'Copiado!' : 'Copiar JSON'}</span>
                </button>
              </div>

              <div className="p-3 bg-[#0b0d10] border border-[#262d35] rounded-lg max-h-96 overflow-y-auto text-[11px] text-[#37d67a]">
                <pre>{snapshot ? JSON.stringify(snapshot, null, 2) : 'Snapshot ainda não disponível.'}</pre>
              </div>
            </div>
          )}

          {/* TAB 5: VULKAN BENCHMARK */}
          {activeTab === 'benchmark' && (
            <div className="space-y-4">
              <div className="bg-[#0b0d10] border border-[#262d35] rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-2">
                      <Zap className="w-4 h-4 text-[#ff334b]" />
                      <span>Vulkan GCN Compute Kernel Benchmark</span>
                    </h3>
                    <p className="text-[11px] text-[#8d98a5] mt-0.5">
                      Submete matrizes FP16/FP32 na fila de computação Vulkan 1.3.
                    </p>
                  </div>

                  <button
                    onClick={onRunBenchmark}
                    disabled={isBenchmarking}
                    className="px-4 py-2 bg-[#ff334b] hover:bg-[#ff203a] text-white font-bold text-xs uppercase tracking-wider rounded transition-all disabled:opacity-50 flex items-center gap-1.5 whitespace-nowrap"
                  >
                    {isBenchmarking ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                    <span>{isBenchmarking ? 'Testando...' : 'Rodar Benchmark'}</span>
                  </button>
                </div>

                {benchmarkLog.length > 0 && (
                  <div className="mt-3 p-3 bg-[#14181d] border border-[#262d35] rounded text-xs space-y-1 max-h-48 overflow-y-auto">
                    {benchmarkLog.map((line, idx) => (
                      <div key={idx} className={
                        line.includes('[OK]') || line.includes('EXCELLENT') ? 'text-[#37d67a]' :
                        line.includes('TFLOPs') || line.includes('Score') ? 'text-[#ff334b] font-bold' :
                        'text-[#8d98a5]'
                      }>
                        {line}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Thermal & Fan Speed Metrics */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-[#0b0d10] border border-[#262d35] rounded p-3 text-xs">
                  <div className="flex items-center gap-2 text-[#8d98a5] mb-1">
                    <Thermometer className="w-3.5 h-3.5 text-[#ff334b]" />
                    <span>TEMPERATURA DA GPU</span>
                  </div>
                  <div className="text-lg font-bold text-white">
                    {currentProfile.temperatureC > 0 ? `${currentProfile.temperatureC} °C` : 'Não informado'}
                  </div>
                  <span className="text-[10px] text-[#8d98a5]">Leitura exibida somente quando fornecida pelo sensor.</span>
                </div>

                <div className="bg-[#0b0d10] border border-[#262d35] rounded p-3 text-xs">
                  <div className="flex items-center gap-2 text-[#8d98a5] mb-1">
                    <ShieldCheck className="w-3.5 h-3.5 text-[#4fa3ff]" />
                    <span>STATUS VULKAN RADV</span>
                  </div>
                  <div className={`text-lg font-bold ${vulkanDetected === false ? 'text-[#ff334b]' : 'text-white'}`}>
                    {vulkanDetected === null ? 'VERIFICANDO' : vulkanDetected ? 'DISPONÍVEL' : 'NÃO DETECTADO'}
                  </div>
                  <span className={`text-[10px] ${vulkanDetected === false ? 'text-[#ff334b]' : 'text-[#37d67a]'}`}>
                    {vulkanDetected === null
                      ? 'Aguardando telemetria real do Engine'
                      : vulkanDetected
                        ? 'Backend Vulkan confirmado pelo Engine [OK]'
                        : 'Vulkan SDK/runtime não confirmado'}
                  </span>
                </div>
              </div>
            </div>
          )}

        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[#262d35] bg-[#14181d] flex items-center justify-between">
          <div className="flex items-center gap-2 text-[11px] text-[#8d98a5]">
            <span className={`w-2 h-2 rounded-full ${loadError ? 'bg-[#ff334b]' : 'bg-[#37d67a]'}`}></span>
            <span>{loadError ? 'AHDE OFFLINE' : 'AHDE TELEMETRY ACTIVE'} • {allSensors.length} SENSOR PROBES</span>
          </div>

          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-white text-black font-bold text-xs uppercase hover:bg-[#e7e7e7] transition-all"
          >
            Fechar Painel
          </button>
        </div>

      </div>
    </div>
  );
};
