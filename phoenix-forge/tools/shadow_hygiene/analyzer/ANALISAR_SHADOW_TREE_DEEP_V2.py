#!/usr/bin/env python3
# PHOENIX SHADOW TREE DEEP ANALYZER V2
# READ-ONLY. Deep-compares divergent shadow files and resolves external references.
# Never moves/deletes/renames/edits project files.

from __future__ import annotations
import argparse, ast, difflib, hashlib, json, os, re, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

TEXT_EXTS={".py",".pyi",".ps1",".bat",".cmd",".sh",".json",".toml",".yaml",".yml",".ini",".cfg",".conf",".md",".txt",".ts",".tsx",".js",".jsx",".mjs",".cjs",".cpp",".cc",".cxx",".c",".h",".hpp",".hxx",".cmake"}
MAX_BYTES=8*1024*1024
EXCLUDE_DIRS={".git",".venv","node_modules","__pycache__",".pytest_cache","backups","archive","repos","temp","tmp","output","outputs"}
EXCLUDE_TOP_RE=[re.compile(r"^architecture_audit_",re.I),re.compile(r"^shadow_tree_verification_",re.I),re.compile(r"^PHOENIX_R6(?:\.|_|$)",re.I),re.compile(r"^phoenix-forge-v\d",re.I)]

def sha256(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest().upper()

def read_text(p):
    try:
        if p.stat().st_size>MAX_BYTES: return None
        return p.read_text(encoding="utf-8",errors="replace")
    except Exception:
        return None

def normalize_text(s):
    return "\n".join(line.rstrip() for line in s.replace("\r\n","\n").replace("\r","\n").split("\n")).strip()

def ast_fingerprint(s):
    try:
        tree=ast.parse(s)
        # Strip positions for semantic-ish equality.
        return ast.dump(tree, annotate_fields=True, include_attributes=False)
    except Exception:
        return None

def extract_symbols(src):
    try:
        tree=ast.parse(src)
    except Exception:
        return {"functions":[],"async_functions":[],"classes":[],"imports":[],"constants":[]}
    out={"functions":[],"async_functions":[],"classes":[],"imports":[],"constants":[]}
    for n in tree.body:
        if isinstance(n,ast.FunctionDef): out["functions"].append(n.name)
        elif isinstance(n,ast.AsyncFunctionDef): out["async_functions"].append(n.name)
        elif isinstance(n,ast.ClassDef): out["classes"].append(n.name)
        elif isinstance(n,ast.Import):
            out["imports"] += [a.name for a in n.names]
        elif isinstance(n,ast.ImportFrom) and n.module:
            out["imports"].append(n.module)
        elif isinstance(n,(ast.Assign,ast.AnnAssign)):
            targets=[]
            if isinstance(n,ast.Assign):
                targets=n.targets
            else:
                targets=[n.target]
            for t in targets:
                if isinstance(t,ast.Name) and t.id.isupper():
                    out["constants"].append(t.id)
    for k in out: out[k]=sorted(set(out[k]))
    return out

def scan_refs(root, shadow_base, shadow_rels):
    refs=[]
    shadow_prefixes=["phoenix_project\\phoenix_kernel","phoenix_project/phoenix_kernel","phoenix_project.phoenix_kernel"]
    rel_tokens={}
    for rel in shadow_rels:
        mod=rel[:-3] if rel.lower().endswith(".py") else rel
        mod=mod.replace("\\",".").replace("/",".")
        if mod.endswith(".__init__"): mod=mod[:-9]
        rel_tokens[rel]=[
            ("phoenix_project\\phoenix_kernel\\"+rel).lower(),
            ("phoenix_project/phoenix_kernel/"+rel.replace("\\","/")).lower(),
            ("phoenix_project.phoenix_kernel."+mod).lower(),
        ]
    for cur,dirs,files in os.walk(root):
        curp=Path(cur)
        try: rel_dir=str(curp.relative_to(root)).replace("/","\\")
        except: rel_dir=""
        kept=[]
        for d in dirs:
            child=(rel_dir+"\\"+d).strip("\\")
            parts=child.split("\\")
            if any(x in EXCLUDE_DIRS for x in parts): continue
            if parts and any(rx.search(parts[0]) for rx in EXCLUDE_TOP_RE): continue
            if child.lower().startswith("phoenix_project\\phoenix_kernel"): continue
            kept.append(d)
        dirs[:]=kept
        for fn in files:
            p=curp/fn
            try: rel=str(p.relative_to(root)).replace("/","\\")
            except: continue
            if p.suffix.lower() not in TEXT_EXTS and p.name not in {"CMakeLists.txt","Makefile","Dockerfile","pyproject.toml","package.json"}:
                continue
            txt=read_text(p)
            if txt is None: continue
            low=txt.lower()
            broad=[t for t in shadow_prefixes if t.lower() in low]
            specifics=[]
            for sr,toks in rel_tokens.items():
                if any(t in low for t in toks):
                    specifics.append(sr)
            if broad or specifics:
                # Keep exact matching lines as evidence.
                lines=[]
                for i,line in enumerate(txt.splitlines(),1):
                    ll=line.lower()
                    if any(t.lower() in ll for t in broad) or any(any(t in ll for t in rel_tokens[sr]) for sr in specifics):
                        lines.append({"line":i,"text":line.strip()[:1000]})
                refs.append({"file":rel,"broad_tokens":broad,"shadow_files":sorted(set(specifics)),"evidence_lines":lines[:100]})
    return refs

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",nargs="?",default=r"C:\PROJETO COMPLETO\PHOENIX 4.5")
    ap.add_argument("--output",default=None)
    args=ap.parse_args()
    root=Path(args.root).resolve()
    canonical=root/"phoenix_kernel"
    shadow=root/"phoenix_project"/"phoenix_kernel"
    if not canonical.exists() or not shadow.exists():
        print("[ERRO] canonical/shadow tree ausente.",file=sys.stderr); return 2

    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    out=Path(args.output).resolve() if args.output else root/f"shadow_tree_deep_analysis_{stamp}"
    out.mkdir(parents=True,exist_ok=True)

    shadow_files={}
    for p in shadow.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            rel=str(p.relative_to(shadow)).replace("/","\\")
            shadow_files[rel]=p

    items=[]
    for rel,sp in sorted(shadow_files.items()):
        cp=canonical/Path(rel.replace("\\",os.sep))
        ssha=sha256(sp)
        csha=sha256(cp) if cp.exists() and cp.is_file() else None
        stxt=read_text(sp)
        ctxt=read_text(cp) if cp.exists() and cp.is_file() else None

        if not cp.exists():
            status="SHADOW_ONLY"
        elif ssha==csha:
            status="IDENTICAL"
        else:
            status="DIFFERENT"

        item={
            "relative_path":rel,
            "status":status,
            "shadow_sha256":ssha,
            "canonical_sha256":csha,
            "shadow_size":sp.stat().st_size,
            "canonical_size":cp.stat().st_size if cp.exists() and cp.is_file() else None,
            "text_analysis":None,
            "python_symbol_diff":None,
        }
        if stxt is not None and ctxt is not None:
            ns,nc=normalize_text(stxt),normalize_text(ctxt)
            sm=difflib.SequenceMatcher(None,nc,ns)
            ratio=sm.ratio()
            sem_same=None
            if sp.suffix.lower()==".py":
                afs,afc=ast_fingerprint(stxt),ast_fingerprint(ctxt)
                sem_same=(afs is not None and afc is not None and afs==afc)
                ss,cs=extract_symbols(stxt),extract_symbols(ctxt)
                item["python_symbol_diff"]={
                    "shadow_only_functions":sorted(set(ss["functions"])-set(cs["functions"])),
                    "canonical_only_functions":sorted(set(cs["functions"])-set(ss["functions"])),
                    "shadow_only_async_functions":sorted(set(ss["async_functions"])-set(cs["async_functions"])),
                    "canonical_only_async_functions":sorted(set(cs["async_functions"])-set(ss["async_functions"])),
                    "shadow_only_classes":sorted(set(ss["classes"])-set(cs["classes"])),
                    "canonical_only_classes":sorted(set(cs["classes"])-set(ss["classes"])),
                    "shadow_only_imports":sorted(set(ss["imports"])-set(cs["imports"])),
                    "canonical_only_imports":sorted(set(cs["imports"])-set(ss["imports"])),
                    "shadow_only_constants":sorted(set(ss["constants"])-set(cs["constants"])),
                    "canonical_only_constants":sorted(set(cs["constants"])-set(ss["constants"])),
                }
            diff=list(difflib.unified_diff(
                ctxt.splitlines(),stxt.splitlines(),
                fromfile="canonical/"+rel,tofile="shadow/"+rel,lineterm="",n=3
            ))
            item["text_analysis"]={
                "normalized_equal":ns==nc,
                "similarity_ratio":round(ratio,6),
                "python_ast_equal":sem_same,
                "unified_diff_preview":diff[:400],
                "diff_truncated":len(diff)>400,
            }
        items.append(item)

    refs=scan_refs(root,shadow,list(shadow_files))
    ref_count=Counter()
    broad_files=[]
    for r in refs:
        broad_files.append(r["file"])
        for sf in r["shadow_files"]: ref_count[sf]+=1

    final=[]
    for item in items:
        rel=item["relative_path"]
        status=item["status"]
        ext=ref_count.get(rel,0)
        ta=item.get("text_analysis") or {}
        sym=item.get("python_symbol_diff") or {}
        if ext>0:
            cls="REFERENCED_SHADOW_COMPONENT"; action="KEEP"
        elif status=="IDENTICAL":
            cls="HIGH_CONFIDENCE_REDUNDANT_COPY"; action="QUARANTINE_CANDIDATE"
        elif status=="DIFFERENT":
            if ta.get("normalized_equal"):
                cls="FORMATTING_ONLY_DIVERGENCE"; action="QUARANTINE_CANDIDATE_AFTER_REFERENCE_CHECK"
            elif ta.get("python_ast_equal") is True:
                cls="SEMANTICALLY_EQUIVALENT_PYTHON"; action="QUARANTINE_CANDIDATE_AFTER_REFERENCE_CHECK"
            else:
                structural_changes=sum(len(v) for v in sym.values()) if sym else 0
                if structural_changes==0 and ta.get("similarity_ratio",0)>=0.98:
                    cls="NEAR_DUPLICATE_NONSTRUCTURAL"; action="MANUAL_DIFF_REVIEW"
                else:
                    cls="FUNCTIONALLY_DIVERGENT_SHADOW"; action="KEEP_AND_RECONCILE"
        else:
            cls="SHADOW_ONLY_COMPONENT"; action="KEEP_AND_REVIEW"

        final.append({
            **item,
            "external_reference_file_count":ext,
            "classification":cls,
            "recommended_action":action,
            "delete_authorized":False,
        })

    counts=Counter(x["classification"] for x in final)
    report={
        "schema":"phoenix.shadow-tree-deep-analysis/v2",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "root":str(root),
        "canonical_root":str(canonical),
        "shadow_root":str(shadow),
        "mode":"READ_ONLY",
        "project_files_modified":False,
        "shadow_file_count":len(shadow_files),
        "classification_counts":dict(counts),
        "external_reference_files":len(refs),
        "status":"COMPLETE",
        "policy":{"no_delete":True,"no_move":True,"no_edit":True,"quarantine_not_executed":True}
    }

    (out/"PHOENIX_SHADOW_DEEP_SUMMARY.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"PHOENIX_SHADOW_DEEP_FILE_ANALYSIS.json").write_text(json.dumps({"items":final},indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"PHOENIX_SHADOW_EXTERNAL_REFERENCE_EVIDENCE.json").write_text(json.dumps({"items":refs},indent=2,ensure_ascii=False),encoding="utf-8")

    md=["# PHOENIX SHADOW TREE — DEEP ANALYSIS V2","",f"Status: **{report['status']}**","",f"Shadow files: {len(shadow_files)}",f"External reference files: {len(refs)}","","## Classifications",""]
    for k,v in counts.most_common():
        md.append(f"- {k}: {v}")
    md += ["","## Regra","",
           "Nenhum arquivo foi movido ou removido.",
           "`FUNCTIONALLY_DIVERGENT_SHADOW` e `REFERENCED_SHADOW_COMPONENT` bloqueiam quarantine automática.",
           "`HIGH_CONFIDENCE_REDUNDANT_COPY`, `FORMATTING_ONLY_DIVERGENCE` e `SEMANTICALLY_EQUIVALENT_PYTHON` são apenas candidatos para a próxima fase."]
    (out/"PHOENIX_SHADOW_DEEP_REPORT.md").write_text("\n".join(md),encoding="utf-8")

    print("="*72)
    print("PHOENIX SHADOW TREE DEEP ANALYZER V2")
    print("="*72)
    print(f"Shadow files:            {len(shadow_files)}")
    print(f"External ref files:      {len(refs)}")
    for k,v in counts.most_common():
        print(f"{k}: {v}")
    print()
    print("READ-ONLY: nenhum arquivo do projeto foi alterado.")
    print(f"Output: {out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
