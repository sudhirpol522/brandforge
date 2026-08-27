from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .config import Settings
from .factory import build_workflow


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill approved BrandForge retrieval sources")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--campaign")
    arguments = parser.parse_args()
    workflow = build_workflow(Settings.from_env())
    summaries = workflow.backfill_retrieval(arguments.tenant, arguments.campaign)
    print(json.dumps([asdict(summary) for summary in summaries], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
