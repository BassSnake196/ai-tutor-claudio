"""Compare recorded architecture/full curriculum artifacts offline."""
import argparse, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.curriculum_eval import validate_curriculum

def main() -> int:
    p=argparse.ArgumentParser(description="Compare recorded curriculum artifacts")
    p.add_argument("--full",type=Path,required=True); p.add_argument("--architecture",type=Path,required=True); p.add_argument("--tasks",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--split",choices=("calibration","dev"),default="calibration")
    a=p.parse_args(); tasks={x["task_id"]:x for x in (json.loads(l) for l in a.tasks.read_text(encoding="utf-8").splitlines() if l.strip()) if x.get("split")==a.split}; results=[]
    for mode,directory in (("full",a.full),("architecture",a.architecture)):
        for path in sorted(directory.glob("*.json")):
            row=json.loads(path.read_text(encoding="utf-8")); task=tasks.get(row.get("task_id")); artifact=row.get("curriculum") if mode=="full" else row.get("architecture")
            if task and artifact: results.append({"task_id":row["task_id"],"mode":mode,**validate_curriculum(task,artifact)})
    a.output.mkdir(parents=True,exist_ok=True); (a.output/"comparison.json").write_text(json.dumps({"split":a.split,"results":results},ensure_ascii=False,indent=2),encoding="utf-8")
    (a.output/"comparison.md").write_text("# Curriculum artifact comparison\n\n"+"\n".join(f"- {r['task_id']} `{r['mode']}`: valid={r['valid']}, richness={r.get('richness',{})}" for r in results),encoding="utf-8")
    return 0
if __name__=="__main__": raise SystemExit(main())
