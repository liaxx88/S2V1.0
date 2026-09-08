import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
for relative in (Path("data/clean"), Path("figures"), Path("tables")):
    target = (root / relative).resolve()
    if root not in target.parents:
        raise RuntimeError(str(target))
    if target.exists():
        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    target.mkdir(parents=True, exist_ok=True)
for relative in (
    "data/clean/nlrb", "data/clean/gate1", "data/clean/results", "data/clean/noaa",
    "data/clean/qcew", "data/clean/gate2", "data/clean/gate3", "data/clean/gate25",
    "data/clean/gate3b", "data/clean/final_pivot", "data/clean/jeem",
    "data/clean/jeem_extension",
):
    (root / relative).mkdir(parents=True, exist_ok=True)
