import React, { useState, useRef, useEffect } from 'react';
import { TerminalEntry } from '../types';
import { Terminal as TerminalIcon, CornerDownLeft, Sparkles, Zap, Trash2, ArrowUp, ArrowDown } from 'lucide-react';

interface TerminalConsoleProps {
  logs: TerminalEntry[];
  onExecuteCommand: (cmd: string) => Promise<void>;
  onClearLogs: () => void;
}

export const TerminalConsole: React.FC<TerminalConsoleProps> = ({
  logs,
  onExecuteCommand,
  onClearLogs
}) => {
  const [inputVal, setInputVal] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [isProcessing, setIsProcessing] = useState(false);
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom when logs change
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [logs]);

  // Keep input focused
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = inputVal.trim();
      if (!cmd) return;

      setHistory(prev => [cmd, ...prev]);
      setHistoryIndex(-1);
      setInputVal('');
      setIsProcessing(true);

      onExecuteCommand(cmd).finally(() => {
        setIsProcessing(false);
        inputRef.current?.focus();
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length > 0) {
        const nextIndex = Math.min(historyIndex + 1, history.length - 1);
        setHistoryIndex(nextIndex);
        setInputVal(history[nextIndex] || '');
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex > 0) {
        const nextIndex = historyIndex - 1;
        setHistoryIndex(nextIndex);
        setInputVal(history[nextIndex] || '');
      } else if (historyIndex === 0) {
        setHistoryIndex(-1);
        setInputVal('');
      }
    }
  };

  const quickChips = [
    { label: 'help', cmd: 'help' },
    { label: 'status', cmd: 'status' },
    { label: 'ports', cmd: 'ports' },
    { label: 'vulkan', cmd: 'vulkan' },
    { label: 'aviary', cmd: 'aviary' },
    { label: 'rag', cmd: 'rag' },
    { label: 'models', cmd: 'models' },
    { label: 'report', cmd: 'report' },
    { label: 'license', cmd: 'license' }
  ];

  return (
    <div className="flex-grow bg-[#08090b] flex flex-col min-h-0 border-t border-[#262d35]">
      
      {/* Terminal Sub-header */}
      <div className="px-4 md:px-8 py-2 border-b border-[#262d35] bg-[#14181d] flex items-center justify-between gap-3 text-xs font-mono text-[#8d98a5]">
        <div className="flex items-center gap-2">
          <TerminalIcon className="w-3.5 h-3.5 text-[#ff334b]" />
          <span className="text-white font-bold uppercase tracking-wider">
            PHOENIX ENGINE & AVIARY CONSOLE
          </span>
          <span className="text-[#3a4450]">|</span>
          <span className="text-[#37d67a] hidden sm:inline">TTY0 ACTIVE (8000 ↔ 3000)</span>
        </div>

        {/* Action Chips */}
        <div className="flex items-center gap-1.5 overflow-x-auto py-0.5">
          <span className="text-[10px] text-[#8d98a5] uppercase mr-1 hidden md:inline">Quick:</span>
          {quickChips.map((chip) => (
            <button
              key={chip.label}
              onClick={() => onExecuteCommand(chip.cmd)}
              className="px-2 py-0.5 rounded bg-[#0b0d10] hover:bg-[#ff334b] text-[#e7e7e7] hover:text-white border border-[#262d35] hover:border-[#ff334b] text-[11px] font-mono transition-colors whitespace-nowrap"
            >
              {chip.label}
            </button>
          ))}

          <button
            onClick={onClearLogs}
            className="p-1 rounded text-[#8d98a5] hover:text-[#ff334b] hover:bg-[#1a1f26] transition-colors ml-1"
            title="Clear terminal screen"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Terminal Output Area */}
      <div
        ref={outputRef}
        onClick={() => inputRef.current?.focus()}
        className="flex-grow p-4 md:p-6 overflow-y-auto font-mono text-sm md:text-[15px] leading-relaxed space-y-1 select-text cursor-text"
      >
        {logs.map((log) => {
          let textClass = 'text-[#e7e7e7]';
          if (log.type === 'sys') textClass = 'text-[#8d98a5]';
          if (log.type === 'ok') textClass = 'text-[#37d67a] font-bold';
          if (log.type === 'err') textClass = 'text-[#ff334b] font-bold';
          if (log.type === 'info') textClass = 'text-[#4fa3ff]';
          if (log.type === 'agent') textClass = 'text-white bg-[#14181d] px-2 py-1 rounded border border-[#262d35] inline-block my-1';

          if (log.type === 'cmd') {
            return (
              <div key={log.id} className="flex items-center gap-2 pt-2 text-white font-bold">
                <span className="text-[#ff334b]">phoenix@aviary:~$</span>
                <span>{log.text}</span>
              </div>
            );
          }

          return (
            <div key={log.id} className={`${textClass} whitespace-pre-wrap`}>
              {log.text}
            </div>
          );
        })}

        {isProcessing && (
          <div className="text-[#ff334b] flex items-center gap-2 text-xs font-mono animate-pulse pt-1">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Executing compute instructions across Port 8000 & 3000...</span>
          </div>
        )}
      </div>

      {/* Terminal Input Bar with Red Prompt */}
      <div className="bg-[#14181d] border-t border-[#262d35] px-4 md:px-6 py-3.5 flex items-center gap-3">
        <span className="text-[#ff334b] font-bold text-sm md:text-base whitespace-nowrap flex items-center gap-1 font-mono">
          phoenix@aviary:~$
        </span>

        <input
          ref={inputRef}
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Comando (help, status, report, ports, vulkan, aviary) ou 'ai <pergunta>'..."
          className="flex-grow bg-transparent border-none text-white text-sm md:text-base font-mono outline-none caret-[#ff334b] placeholder-[#8d98a5]/50"
          autoFocus
          autoComplete="off"
          spellCheck="false"
        />

        <button
          onClick={() => {
            if (!inputVal.trim()) return;
            const cmd = inputVal.trim();
            setHistory(prev => [cmd, ...prev]);
            setInputVal('');
            onExecuteCommand(cmd);
          }}
          className="p-1.5 rounded bg-[#ff334b] hover:bg-[#ff203a] text-white transition-colors"
          title="Send command"
        >
          <CornerDownLeft className="w-4 h-4" />
        </button>
      </div>

    </div>
  );
};
