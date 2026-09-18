from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
from typing import Any
from phoenix_forge.util import powershell_json

def whea_events(minutes: int = 60, max_events: int = 50) -> dict[str, Any]:
    """Read recent WHEA hardware error events. Read-only Phoenix hardware-correctness watchdog input."""
    if os.name != 'nt': return {'available':False,'events':[],'reason':'Windows WHEA only'}
    minutes=max(1,min(int(minutes),7*24*60)); max_events=max(1,min(int(max_events),500))
    script=rf'''
$start=(Get-Date).AddMinutes(-{minutes})
$rows=Get-WinEvent -FilterHashtable @{{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; StartTime=$start}} -ErrorAction SilentlyContinue |
 Select-Object -First {max_events} TimeCreated,Id,LevelDisplayName,MachineName,Message
$rows | ConvertTo-Json -Compress -Depth 4
'''
    data=powershell_json(script)
    if not data:return {'available':True,'events':[],'count':0,'window_minutes':minutes}
    rows=data if isinstance(data,list) else [data]
    return {'available':True,'events':rows,'count':len(rows),'window_minutes':minutes}

def snapshot(minutes:int=60)->dict[str,Any]:
    return {'whea':whea_events(minutes)}
