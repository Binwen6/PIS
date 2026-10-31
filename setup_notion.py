"""Optional: create the PIS sub-structure locally (the daily run also does this automatically).

  NOTION_TOKEN=ntn_xxx python setup_notion.py
"""
from pathlib import Path

import yaml

from pis import bootstrap
from pis.notion import Notion

if __name__ == "__main__":
    root = Path(__file__).parent
    cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text(encoding="utf-8"))
    for k, v in bootstrap.ensure(Notion(), cfg, root).items():
        print(f"{k:8s} {v}")
