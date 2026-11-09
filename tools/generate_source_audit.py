"""Generate a traceable line-by-line review register for the pinned repository.

Usage:
  python tools/generate_source_audit.py --out source_line_review.csv

One record is produced for each text line in tracked code/config, with a
source SHA256 and nearest AST function/class owner when Python parsing works.
The generated Review status is intentionally UNREVIEWED: a parser does not
replace human examination or formal assurance. Reviewers can record findings
and signoff in a working spreadsheet derived from this CSV.
"""
import argparse
import ast
import csv
from hashlib import sha256
from pathlib import Path
import subprocess

INCLUDE={".py",".js",".json",".yaml",".yml",".toml",".ini",".css",".html",".bat",".sh"}
COLUMNS=("path","file_sha256","line","scope","classification","source","review_status",
         "reviewer","finding_id","review_date","notes")


def tracked(root):
    result=subprocess.run(["git","ls-files","-z"],cwd=root,check=True,
                          stdout=subprocess.PIPE)
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        path=Path(entry.decode("utf-8","surrogateescape"))
        if path.suffix.lower() not in INCLUDE:
            continue
        if any(p in ("vendor","node_modules",".venv","dist","build","__pycache__") for p in path.parts):
            continue
        yield path


def scopes_python(source):
    """Find smallest enclosing AST def/class for each source line."""
    root=ast.parse(source)
    scopes=[]
    for node in ast.walk(root):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            end=getattr(node,"end_lineno",node.lineno)
            scopes.append((node.lineno,end,node.name))
    return scopes


def classify(line,suffix):
    t=line.strip()
    if not t:
        return "blank"
    if t.startswith(("#","//","/*","*")):
        return "comment"
    if suffix==".py" and t.startswith(("import ","from ")):
        return "import"
    if suffix==".py" and t.startswith(("def ","async def ","class ","@")):
        return "declaration"
    if suffix in (".yaml",".yml",".json",".toml",".ini"):
        return "configuration"
    return "source"


def generate(root,output):
    count=0
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=COLUMNS)
        writer.writeheader()
        for path in tracked(root):
            full=root/path
            try:
                blob=full.read_bytes()
                source=blob.decode("utf-8")
            except (OSError,UnicodeError):
                continue
            scopes=[]
            if path.suffix.lower()==".py":
                try:
                    scopes=scopes_python(source)
                except SyntaxError:
                    scopes=[]
            digest=sha256(blob).hexdigest()
            for lineno,line in enumerate(source.splitlines(),1):
                covering=[(end-start,scope) for start,end,scope in scopes
                          if start<=lineno<=end]
                owner=min(covering,default=(0,"module"))[1]
                # Standard CSV escaping handles quotes and delimiters.
                writer.writerow({
                    "path":path.as_posix(),"file_sha256":digest,
                    "line":lineno,"scope":owner,
                    "classification":classify(line,path.suffix.lower()),
                    "source":line,"review_status":"UNREVIEWED",
                    "reviewer":"","finding_id":"","review_date":"","notes":""
                })
                count+=1
    return count


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="source_line_review.csv")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=Path(args.out).resolve()
    if out.is_relative_to(root):
        # Prevent overwriting tracked source file via a malicious output path.
        tracked_paths={str((root/p).resolve()) for p in tracked(root)}
        if str(out) in tracked_paths:
            parser.error("Output must not overwrite a tracked repository file.")
    n=generate(root,out)
    print(f"Wrote {n} source lines to {out}; all marked UNREVIEWED.")


if __name__=="__main__":
    main()
