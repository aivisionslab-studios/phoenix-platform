from __future__ import annotations
from pathlib import Path
import argparse, json, re, sys, tomllib

VERSION_RE = re.compile(r"0\.25\.0rc\d+(?:\.post\d+)?")
UA_RE = re.compile(r"Phoenix-Forge/(0\.25\.0rc\d+(?:\.post\d+)?)")


def canonical_version(root: Path) -> str:
    p = root / "payload" / "pyproject.toml"
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    v = str(data.get("project", {}).get("version", "")).strip()
    if not v:
        raise RuntimeError("project.version missing from payload/pyproject.toml")
    return v


def filename_version(path: Path):
    m = VERSION_RE.search(path.name)
    return m.group(0) if m else None


def first_h1(path: Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def scan(root: Path):
    canonical = canonical_version(root)
    stale=[]; current=[]; historical=[]
    files_scanned=0

    def stale_add(path, kind, found, expected, detail=""):
        stale.append({"file":str(path.relative_to(root)).replace('\\','/'),"kind":kind,"found":found,"expected":expected,"detail":detail})

    # pyproject is the sole canonical source.
    current.append({"file":"payload/pyproject.toml","kind":"canonical_version","value":canonical})

    # Every versioned top-level JSON must be internally self-consistent with its filename.
    for path in root.glob("*.json"):
        files_scanned += 1
        fv=filename_version(path)
        if not fv: continue
        try: data=json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            stale_add(path,"invalid_json",str(e),"valid JSON"); continue
        vals=[]
        for key in ("release","version","new_version"):
            if isinstance(data,dict) and key in data and isinstance(data[key],str) and VERSION_RE.fullmatch(data[key]): vals.append((key,data[key]))
        for key,val in vals:
            if val != fv: stale_add(path,f"json.{key}",val,fv,"versioned artifact must match its filename")
        bucket=current if fv==canonical else historical
        bucket.append({"file":path.name,"kind":"versioned_json","value":fv})

    # Versioned changelog/audit markdowns are historical or current according to filename and first heading.
    for path in list(root.glob("CHANGELOG_*.md"))+list((root/'payload').glob("CHANGELOG_*.md")):
        files_scanned += 1
        fv=filename_version(path)
        if not fv: continue
        h=first_h1(path)
        hm=VERSION_RE.search(h)
        if hm and hm.group(0)!=fv: stale_add(path,"first_heading",hm.group(0),fv,"versioned changelog heading mismatch")
        bucket=current if fv==canonical else historical
        bucket.append({"file":str(path.relative_to(root)).replace('\\','/'),"kind":"versioned_markdown","value":fv})

    # Unversioned current changelog must start with canonical version.
    ch=root/'payload'/'CHANGELOG.md'; files_scanned += 1
    if not ch.exists(): stale_add(ch,"missing","missing",canonical)
    else:
        h=first_h1(ch); m=VERSION_RE.search(h)
        found=m.group(0) if m else None
        if found!=canonical: stale_add(ch,"current_changelog_heading",found,canonical)
        else: current.append({"file":"payload/CHANGELOG.md","kind":"current_changelog","value":found})

    # Active source may not hard-code a divergent Phoenix-Forge User-Agent.
    src=root/'payload'/'phoenix_forge'
    for path in src.rglob('*.py'):
        files_scanned += 1
        if 'tests' in path.parts: continue
        text=path.read_text(encoding='utf-8',errors='replace')
        for m in UA_RE.finditer(text):
            if m.group(1)!=canonical: stale_add(path,"hardcoded_user_agent",m.group(1),canonical)
            else: current.append({"file":str(path.relative_to(root)).replace('\\','/'),"kind":"hardcoded_user_agent","value":m.group(1)})

    # Current installer/test scripts must be named for and explicitly expect canonical version.
    expected_names=[f'Aplicar_Forge_{canonical}.ps1',f'TESTAR_Forge_{canonical}.ps1',f'Aplicar_Forge_{canonical}.bat',f'TESTAR_Forge_{canonical}.bat']
    for name in expected_names:
        path=root/name; files_scanned += 1
        if not path.exists(): stale_add(path,"missing_current_release_file","missing",canonical); continue
        text=path.read_text(encoding='utf-8',errors='replace')
        if canonical not in text: stale_add(path,"canonical_label_missing","missing",canonical)
        else: current.append({"file":name,"kind":"current_release_script","value":canonical})

    # Active package identity must equal pyproject.
    init=root/'payload'/'phoenix_forge'/'__init__.py'; files_scanned += 1
    txt=init.read_text(encoding='utf-8',errors='replace') if init.exists() else ''
    m=re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]",txt)
    found=m.group(1) if m else None
    if found!=canonical: stale_add(init,"package_version",found,canonical)
    else: current.append({"file":"payload/phoenix_forge/__init__.py","kind":"package_version","value":found})

    result="PASS" if not stale else "FAIL"
    return {"schema":"phoenix.forge.release-metadata-truth/v1","canonical_version":canonical,"files_scanned":files_scanned,
            "current_release_labels":current,"historical_labels":historical,"stale_labels":stale,"result":result,
            "policy":{"pyproject_is_canonical":True,"historical_labels_allowed_when_explicit":True,"stale_current_labels_block_build":True}}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--output'); ap.add_argument('--strict',action='store_true')
    a=ap.parse_args(); root=Path(a.root).resolve(); report=scan(root)
    payload=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
    if a.output:
        op=Path(a.output); op.parent.mkdir(parents=True,exist_ok=True); op.write_text(payload,encoding='utf-8')
    print(payload,end='')
    if a.strict and report['result']!='PASS': return 2
    return 0
if __name__=='__main__': raise SystemExit(main())
