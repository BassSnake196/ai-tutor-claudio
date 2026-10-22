"""Clone the production collection into an explicitly isolated evaluation collection."""
import argparse, asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.backends import clone_collection

def main() -> int:
    p = argparse.ArgumentParser(description="Safely clone Qdrant data for evaluation")
    p.add_argument("--url", default="http://localhost:6333"); p.add_argument("--source", default="tutor_documents")
    p.add_argument("--destination", required=True); p.add_argument("--recreate", action="store_true")
    a = p.parse_args(); print(asyncio.run(clone_collection(url=a.url, source=a.source, destination=a.destination, recreate=a.recreate))); return 0
if __name__ == "__main__": raise SystemExit(main())
