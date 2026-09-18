from __future__ import annotations
import hashlib,os,time,zipfile
from pathlib import Path,PurePosixPath
from typing import Any

def inspect_zip(path:str,max_member_bytes:int=20*1024**3,max_ratio:float=1000)->dict[str,Any]:
    p=Path(path);started=time.monotonic();issues=[];members=[];seen=set();total=0
    if not p.is_file():
        return {'schema':'phoenix.forge.archive-integrity/v1','path':str(p),'archive_bytes':None,'sha256':None,
          'status':'NOT_FOUND','passed':False,'member_count':0,'uncompressed_bytes':0,
          'issues':[{'code':'NOT_FOUND','message':'Archive path does not exist or is not a file'}],'members':[],
          'duration_s':round(time.monotonic()-started,3)}
    sha=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):sha.update(block)
    try:
        with zipfile.ZipFile(p) as z:
            bad=z.testzip()
            if bad:issues.append({'code':'CRC_ERROR','member':bad})
            for info in z.infolist():
                name=info.filename;parts=PurePosixPath(name).parts;ratio=info.file_size/max(1,info.compress_size);total+=info.file_size
                row={'name':name,'size':info.file_size,'compressed_size':info.compress_size,'crc32':f'{info.CRC:08x}','ratio':round(ratio,2)};members.append(row)
                if name in seen:issues.append({'code':'DUPLICATE_NAME','member':name})
                seen.add(name)
                if name.startswith(('/', '\\')) or '..' in parts:issues.append({'code':'PATH_TRAVERSAL','member':name})
                if info.file_size>max_member_bytes:issues.append({'code':'MEMBER_TOO_LARGE','member':name,'size':info.file_size})
                if ratio>max_ratio and info.file_size>1024**2:issues.append({'code':'SUSPICIOUS_RATIO','member':name,'ratio':ratio})
        status='PASS' if not issues else 'FAILED'
    except Exception as exc:status='INVALID_ZIP';issues.append({'code':'OPEN_ERROR','message':str(exc)})
    return {'schema':'phoenix.forge.archive-integrity/v1','path':str(p),'archive_bytes':p.stat().st_size if p.exists() else None,
      'sha256':sha.hexdigest(),'status':status,'passed':status=='PASS','member_count':len(members),'uncompressed_bytes':total,
      'issues':issues,'members':members,'duration_s':round(time.monotonic()-started,3)}
