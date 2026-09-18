#!/usr/bin/env python3
# PHOENIX SHADOW REFERENCE RESOLVER V3
# READ-ONLY. Classifies every external reference to phoenix_project/phoenix_kernel
# and distinguishes operational dependencies from audit/tool/history noise.

from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone

TEXT_EXTS={".py",".pyi",".ps1",".bat",".cmd",".sh",".json",".toml",".yaml",".yml",".ini",".cfg",".conf",".md",".txt",".ts",".tsx",".js",".jsx",".mjs",".cjs",".cpp",".cc",".cxx",".c",".h",".hpp",".hxx",".cmake"}
MAX_BYTES=8*1024*1024

NOISE_TOP_PREFIXES=(
    "architecture_audit_",
    "architecture_audit_active_",
    "shadow_tree_verification_",
    "shadow_tree_deep_analysis_",
    "shadow_reference_resolution_",
    "PHOENIX_ACTIVE_ARCHITECTURE_AUDITOR",
    "PHOENIX_SHADOW_TREE_VERIFIER",
    "PHOENIX_SHADOW_TREE_DEEP_ANALYZER",
    "PHOENIX_ARCHITECTURE_TRIAGE",
)
HISTORY_TOP_RE=[
    re.compile(r"^PHOENIX_R6(?:\.|_|$)",re.I),
    re.compile(r"^phoenix-forge-v\d",re.I),
]
EXCLUDE_DIR_NAMES={".git",".venv","node_modules","__pycache__",".pytest_cache","backups","archive","repos","temp","tmp","output","outputs"}

def read_text(p:Path):
    try:
        if p.stat().st_size>MAX_BYTES: return None
        return p.read_text(encoding="utf-8",errors="replace")
    except Exception:
        return None

def relnorm(p:Path,root:Path)->str:
    return str(p.relative_to(root)).replace("/","\\")

def classify_source(rel:str)->str:
    q=rel.lower().replace("/","\\")
    top=q.split("\\",1)[0]
    if top.startswith(tuple(x.lower() for x in NOISE_TOP_PREFIXES)):
        return "AUDIT_TOOL_NOISE"
    if any(rx.search(top) for rx in HISTORY_TOP_RE):
        return "HISTORY_NOISE"
    if q.startswith("tests\\") or q.startswith("payload\\tests\\") or "\\tests\\" in q or q.startswith("public_guard\\tests\\"):
        return "TEST_REFERENCE"
    if q.startswith("public_guard\\") or q.startswith("install\\") or q.startswith("bin\\"):
        return "TOOLING_REFERENCE"
    if q.startswith("phoenix-forge\\"):
        return "FORGE_REFERENCE"
    if q.startswith("phoenix_kernel\\") or q in ("api_server.py","kernel.py") or q.startswith("core\\") or q.startswith("hardware_engine\\"):
        return "ENGINE_RUNTIME_REFERENCE"
    if q.startswith("platform_source\\"):
        return "AVIARY_REFERENCE"
    if q.startswith("src\\phoenix-llama-runtime\\"):
        return "LLAMA_RUNTIME_REFERENCE"
    if q.startswith("src\\phoenix-diffusion.cpp\\"):
        return "DIFFUSION_RUNTIME_REFERENCE"
    if q.startswith("phoenix_project\\") and not q.startswith("phoenix_project\\phoenix_kernel\\"):
        return "PHOENIX_PROJECT_REFERENCE"
    if q.startswith("docs\\") or q.endswith(".md") or q.endswith(".txt"):
        return "DOCUMENTATION_REFERENCE"
    return "OTHER_REFERENCE"

def should_scan(rel:str,p:Path)->bool:
    q=rel.replace("/","\\")
    parts=q.split("\\")
    if any(part in EXCLUDE_DIR_NAMES for part in parts):
        return False
    top=parts[0]
    if any(rx.search(top) for rx in HISTORY_TOP_RE):
        return False
    if q.lower().startswith("phoenix_project\\phoenix_kernel\\"):
        return False
    if p.suffix.lower() in TEXT_EXTS or p.name in {"CMakeLists.txt","Makefile","Dockerfile","pyproject.toml","package.json"}:
        return True
    return False

def module_name(rel:str)->str:
    m=rel[:-3] if rel.lower().endswith(".py") else rel
    m=m.replace("\\",".").replace("/",".")
    if m.endswith(".__init__"): m=m[:-9]
    return m

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",nargs="?",default=r"C:\PROJETO COMPLETO\PHOENIX 4.5")
    ap.add_argument("--output",default=None)
    args=ap.parse_args()
    root=Path(args.root).resolve()
    shadow=root/"phoenix_project"/"phoenix_kernel"
    canonical=root/"phoenix_kernel"
    if not shadow.exists() or not canonical.exists():
        print("[ERRO] shadow/canonical tree ausente.",file=sys.stderr); return 2

    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    out=Path(args.output).resolve() if args.output else root/f"shadow_reference_resolution_{stamp}"
    out.mkdir(parents=True,exist_ok=True)

    shadow_rels=[]
    for p in shadow.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            shadow_rels.append(str(p.relative_to(shadow)).replace("/","\\"))

    tokens={}
    for rel in shadow_rels:
        mod=module_name(rel)
        tokens[rel]={
            "path_backslash":("phoenix_project\\phoenix_kernel\\"+rel).lower(),
            "path_slash":("phoenix_project/phoenix_kernel/"+rel.replace("\\","/")).lower(),
            "module":("phoenix_project.phoenix_kernel."+mod).lower(),
            "canonical_module":("phoenix_kernel."+mod).lower(),
        }

    refs=[]
    per_shadow=defaultdict(list)
    files_scanned=0

    for cur,dirs,files in os.walk(root):
        curp=Path(cur)
        try: rel_dir=relnorm(curp,root) if curp!=root else ""
        except Exception: rel_dir=""

        kept=[]
        for d in dirs:
            child=(rel_dir+"\\"+d).strip("\\")
            parts=child.split("\\")
            if any(x in EXCLUDE_DIR_NAMES for x in parts): continue
            if child.lower().startswith("phoenix_project\\phoenix_kernel"): continue
            if any(rx.search(parts[0]) for rx in HISTORY_TOP_RE): continue
            kept.append(d)
        dirs[:]=kept

        for fn in files:
            p=curp/fn
            try: rel=relnorm(p,root)
            except Exception: continue
            if not should_scan(rel,p): continue
            txt=read_text(p)
            if txt is None: continue
            files_scanned+=1
            low=txt.lower()

            matched=[]
            line_hits=[]
            for sf,t in tokens.items():
                matched_kinds=[]
                if t["path_backslash"] in low: matched_kinds.append("PATH_BACKSLASH")
                if t["path_slash"] in low: matched_kinds.append("PATH_SLASH")
                if t["module"] in low: matched_kinds.append("PYTHON_MODULE")
                if matched_kinds:
                    matched.append((sf,matched_kinds))
            if not matched:
                continue

            for i,line in enumerate(txt.splitlines(),1):
                ll=line.lower()
                for sf,kinds in matched:
                    t=tokens[sf]
                    if t["path_backslash"] in ll or t["path_slash"] in ll or t["module"] in ll:
                        line_hits.append({"line":i,"shadow_file":sf,"text":line.strip()[:1200]})

            src_class=classify_source(rel)
            rec={
                "source_file":rel,
                "source_classification":src_class,
                "matches":[{"shadow_file":sf,"match_kinds":kinds} for sf,kinds in matched],
                "evidence_lines":line_hits[:300],
            }
            refs.append(rec)
            for sf,kinds in matched:
                per_shadow[sf].append({
                    "source_file":rel,
                    "source_classification":src_class,
                    "match_kinds":kinds,
                })

    # Resolve each shadow file.
    operational_classes={
        "ENGINE_RUNTIME_REFERENCE","FORGE_REFERENCE","AVIARY_REFERENCE",
        "LLAMA_RUNTIME_REFERENCE","DIFFUSION_RUNTIME_REFERENCE","TOOLING_REFERENCE"
    }
    benign_classes={"TEST_REFERENCE","DOCUMENTATION_REFERENCE","AUDIT_TOOL_NOISE","HISTORY_NOISE"}
    resolved=[]
    for sf in sorted(shadow_rels):
        srcs=per_shadow.get(sf,[])
        cnt=Counter(x["source_classification"] for x in srcs)
        operational=[x for x in srcs if x["source_classification"] in operational_classes]
        project_refs=[x for x in srcs if x["source_classification"]=="PHOENIX_PROJECT_REFERENCE"]
        other=[x for x in srcs if x["source_classification"]=="OTHER_REFERENCE"]
        benign=[x for x in srcs if x["source_classification"] in benign_classes]

        if operational:
            verdict="OPERATIONAL_REFERENCE_CONFIRMED"
            action="BLOCK_QUARANTINE"
        elif project_refs:
            verdict="PROJECT_INTERNAL_REFERENCE"
            action="REVIEW_BEFORE_QUARANTINE"
        elif other:
            verdict="UNCLASSIFIED_REFERENCE"
            action="REVIEW_BEFORE_QUARANTINE"
        elif benign:
            verdict="NON_OPERATIONAL_REFERENCE_ONLY"
            action="QUARANTINE_ELIGIBLE_IF_CONTENT_SAFE"
        else:
            verdict="NO_EXTERNAL_REFERENCE"
            action="QUARANTINE_ELIGIBLE_IF_CONTENT_SAFE"

        resolved.append({
            "shadow_file":sf,
            "reference_counts":dict(cnt),
            "operational_reference_count":len(operational),
            "project_internal_reference_count":len(project_refs),
            "benign_reference_count":len(benign),
            "other_reference_count":len(other),
            "verdict":verdict,
            "recommended_action":action,
            "sources":srcs,
        })

    ref_class_counts=Counter(r["source_classification"] for r in refs)
    verdict_counts=Counter(r["verdict"] for r in resolved)

    summary={
        "schema":"phoenix.shadow-reference-resolution/v3",
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "root":str(root),
        "mode":"READ_ONLY",
        "project_files_modified":False,
        "files_scanned":files_scanned,
        "shadow_files":len(shadow_rels),
        "reference_source_files":len(refs),
        "reference_source_classification_counts":dict(ref_class_counts),
        "shadow_verdict_counts":dict(verdict_counts),
        "operationally_referenced_shadow_files":sum(1 for r in resolved if r["verdict"]=="OPERATIONAL_REFERENCE_CONFIRMED"),
        "status":"COMPLETE",
    }

    (out/"PHOENIX_SHADOW_REFERENCE_SUMMARY.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"PHOENIX_SHADOW_REFERENCE_SOURCES.json").write_text(json.dumps({"items":refs},indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"PHOENIX_SHADOW_REFERENCE_RESOLUTION.json").write_text(json.dumps({"items":resolved},indent=2,ensure_ascii=False),encoding="utf-8")

    md=["# PHOENIX SHADOW REFERENCE RESOLVER V3","",f"Status: **{summary['status']}**","",
        f"Shadow files: {len(shadow_rels)}",f"Reference source files: {len(refs)}",
        f"Operationally referenced shadow files: {summary['operationally_referenced_shadow_files']}","","## Source classes",""]
    for k,v in ref_class_counts.most_common():
        md.append(f"- {k}: {v}")
    md += ["","## Shadow verdicts",""]
    for k,v in verdict_counts.most_common():
        md.append(f"- {k}: {v}")
    md += ["","## Rule","",
           "Only `OPERATIONAL_REFERENCE_CONFIRMED` blocks quarantine outright.",
           "`TEST_REFERENCE`, documentation and audit-tool references are non-operational evidence and must not be treated as runtime dependencies.",
           "This tool performs no MOVE/DELETE/EDIT."]
    (out/"PHOENIX_SHADOW_REFERENCE_REPORT.md").write_text("\n".join(md),encoding="utf-8")

    print("="*72)
    print("PHOENIX SHADOW REFERENCE RESOLVER V3")
    print("="*72)
    print(f"Files scanned:                     {files_scanned}")
    print(f"Shadow files:                      {len(shadow_rels)}")
    print(f"Reference source files:            {len(refs)}")
    print(f"Operationally referenced shadows: {summary['operationally_referenced_shadow_files']}")
    print()
    print("Reference source classes:")
    for k,v in ref_class_counts.most_common():
        print(f"  {k}: {v}")
    print()
    print("Shadow verdicts:")
    for k,v in verdict_counts.most_common():
        print(f"  {k}: {v}")
    print()
    print("READ-ONLY: nenhum arquivo do projeto foi alterado.")
    print(f"Output: {out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
