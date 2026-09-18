from __future__ import annotations
import hashlib, json, os, random, statistics, tempfile, time
from pathlib import Path
from phoenix_forge.models import StressResult
from phoenix_forge.util import powershell_json,run,which

def health_inventory()->dict:
    """Read-only SMART/NVMe health inventory; never starts a destructive/self test."""
    if os.name=="nt":
        script=r'''
$out=@()
Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
  $d=$_
  $r=$null
  try {$r=Get-StorageReliabilityCounter -PhysicalDisk $d -ErrorAction Stop} catch {}
  $out += [pscustomobject]@{
    FriendlyName=$d.FriendlyName;SerialNumber=$d.SerialNumber;MediaType=[string]$d.MediaType
    BusType=[string]$d.BusType;HealthStatus=[string]$d.HealthStatus;OperationalStatus=[string]$d.OperationalStatus
    Size=$d.Size;Temperature=if($r){$r.Temperature}else{$null};Wear=if($r){$r.Wear}else{$null}
    ReadErrorsTotal=if($r){$r.ReadErrorsTotal}else{$null};WriteErrorsTotal=if($r){$r.WriteErrorsTotal}else{$null}
    PowerOnHours=if($r){$r.PowerOnHours}else{$null}
  }
}
$out | ConvertTo-Json -Compress
'''
        rows=powershell_json(script) or [];rows=rows if isinstance(rows,list) else [rows]
        return {"schema":"phoenix.forge.storage-health/v1","provider":"Windows Storage Management","available":bool(rows),"devices":rows}
    smart=which("smartctl");nvme=which("nvme");rows=[]
    if smart:
        c,o,_=run([smart,"--scan-open","--json"],timeout=20)
        if c==0:
            try:
                for item in json.loads(o).get("devices",[]):
                    name=item.get("name");rc,raw,_=run([smart,"-a",name,"--json"],timeout=30)
                    if rc in (0,4):
                        try:rows.append(json.loads(raw))
                        except ValueError:pass
            except ValueError:pass
    if nvme and not rows:
        c,o,_=run([nvme,"list","-o","json"],timeout=20)
        if c==0:
            try:rows=json.loads(o).get("Devices",[])
            except ValueError:pass
    return {"schema":"phoenix.forge.storage-health/v1","provider":"smartctl" if smart else ("nvme-cli" if nvme else None),
      "available":bool(rows),"devices":rows,"read_only":True}

def sequential_bench(size_mb:int=256, block_mb:int=4, directory:str|None=None)->StressResult:
    """Bounded sequential storage validation/throughput benchmark using a temporary file."""
    size_mb=max(16,min(int(size_mb),4096)); block_mb=max(1,min(int(block_mb),64))
    total=size_mb*1024*1024; block=block_mb*1024*1024
    base=Path(directory) if directory else Path(tempfile.gettempdir())
    base.mkdir(parents=True,exist_ok=True); path=base/f'phoenix_forge_storage_{os.getpid()}.bin'
    seed=hashlib.sha256(b'Phoenix Forge storage validation').digest(); data=(seed*((block+len(seed)-1)//len(seed)))[:block]
    st=time.monotonic(); write_s=read_s=0.0; digest_w=hashlib.sha256(); digest_r=hashlib.sha256()
    try:
        t=time.monotonic()
        with path.open('wb', buffering=0) as f:
            remain=total
            while remain:
                chunk=data[:min(block,remain)]; f.write(chunk); digest_w.update(chunk); remain-=len(chunk)
            f.flush(); os.fsync(f.fileno())
        write_s=time.monotonic()-t
        t=time.monotonic()
        with path.open('rb', buffering=0) as f:
            while True:
                b=f.read(block)
                if not b:break
                digest_r.update(b)
        read_s=time.monotonic()-t
        passed=digest_w.digest()==digest_r.digest()
        return StressResult(module='Phoenix Storage / Sequential',passed=passed,duration_s=time.monotonic()-st,
            metrics={'status':'PASS' if passed else 'DATA_MISMATCH','size_mb':size_mb,'block_mb':block_mb,
                     'write_mb_s':round(size_mb/max(write_s,1e-9),2),'read_mb_s':round(size_mb/max(read_s,1e-9),2),
                     'sha256':digest_r.hexdigest(),'path_root':str(base)},
            warnings=['OS/filesystem caching can affect throughput; this is a validation-oriented benchmark, not a replacement for dedicated storage suites.'])
    finally:
        try:path.unlink(missing_ok=True)
        except Exception:pass

def _pct(values:list[float],p:float)->float:
    values=sorted(values);pos=(len(values)-1)*p/100;lo=int(pos);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)

def random_bench(size_mb:int=64,block_kb:int=4,operations:int=2000,directory:str|None=None)->StressResult:
    """Deterministic random read/write latency and IOPS with readback validation."""
    size_mb=max(16,min(int(size_mb),2048));block_kb=max(4,min(int(block_kb),1024));operations=max(100,min(int(operations),100000))
    total=size_mb*1024*1024;block=block_kb*1024;slots=max(1,total//block)
    base=Path(directory) if directory else Path(tempfile.gettempdir());base.mkdir(parents=True,exist_ok=True)
    path=base/f"phoenix_forge_random_{os.getpid()}.bin";rng=random.Random(0x50484F454E4958)
    payload=bytes((i*29+7)&255 for i in range(block));writes=[];reads=[];chosen=[rng.randrange(slots) for _ in range(operations)]
    started=time.perf_counter();passed=True
    try:
        with path.open("w+b",buffering=0) as f:
            f.truncate(total)
            for slot in chosen:
                t=time.perf_counter_ns();f.seek(slot*block);f.write(payload);writes.append((time.perf_counter_ns()-t)/1e6)
            f.flush();os.fsync(f.fileno())
            for slot in chosen:
                t=time.perf_counter_ns();f.seek(slot*block);data=f.read(block);reads.append((time.perf_counter_ns()-t)/1e6)
                if data!=payload:passed=False;break
        elapsed=time.perf_counter()-started
        def stats(v):
            return {"min_ms":round(min(v),4),"p50_ms":round(_pct(v,50),4),"p95_ms":round(_pct(v,95),4),
              "p99_ms":round(_pct(v,99),4),"max_ms":round(max(v),4),"avg_ms":round(statistics.fmean(v),4)}
        return StressResult(module="Phoenix Storage / Random",passed=passed,duration_s=elapsed,
          metrics={"status":"PASS" if passed else "DATA_MISMATCH","size_mb":size_mb,"block_kb":block_kb,
            "operations":operations,"write_iops":round(1000/max(statistics.fmean(writes),1e-9),2),
            "read_iops":round(1000/max(statistics.fmean(reads),1e-9),2),
            "write_latency":stats(writes),"read_latency":stats(reads),"correctness_verified":passed},
          warnings=["Filesystem cache and device write cache affect results; compare identical profiles and power policies."])
    finally:
        try:path.unlink(missing_ok=True)
        except Exception:pass
