from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class JobPaths:
    job_id: str
    base_dir: str

    @property
    def json_path(self) -> str:
        return os.path.join(self.base_dir, f"{self.job_id}.json")

    @property
    def pdf_path(self) -> str:
        return os.path.join(self.base_dir, f"{self.job_id}.pdf")

    @property
    def xlsx_path(self) -> str:
        return os.path.join(self.base_dir, f"{self.job_id}.xlsx")


class JobStore:
    """
    Simple file-based store.
    - Writes JSON + generated outputs to disk
    - Allows download later by job_id
    - Cleans old jobs optionally
    """

    def __init__(self, base_dir: str = "/tmp/test_case_jobs", ttl_seconds: int = 24 * 3600) -> None:
        self.base_dir = base_dir
        self.ttl_seconds = ttl_seconds
        os.makedirs(self.base_dir, exist_ok=True)

    def new_job_id(self) -> str:
        return uuid.uuid4().hex

    def paths(self, job_id: str) -> JobPaths:
        return JobPaths(job_id=job_id, base_dir=self.base_dir)

    def save_json(self, job_id: str, payload: Dict[str, Any]) -> None:
        paths = self.paths(job_id)
        payload2 = dict(payload)
        payload2["_meta"] = {"saved_at": int(time.time())}
        with open(paths.json_path, "w", encoding="utf-8") as f:
            json.dump(payload2, f, ensure_ascii=False, indent=2)

    def load_json(self, job_id: str) -> Optional[Dict[str, Any]]:
        paths = self.paths(job_id)
        if not os.path.exists(paths.json_path):
            return None
        with open(paths.json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self, job_id: str) -> bool:
        return os.path.exists(self.paths(job_id).json_path)

    def cleanup_old(self) -> None:
        now = int(time.time())
        for name in os.listdir(self.base_dir):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.base_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_at = int(data.get("_meta", {}).get("saved_at", 0))
                if saved_at and (now - saved_at) > self.ttl_seconds:
                    job_id = name.replace(".json", "")
                    paths = self.paths(job_id)
                    for p in (paths.json_path, paths.pdf_path, paths.xlsx_path):
                        if os.path.exists(p):
                            os.remove(p)
            except Exception:
                # Best-effort cleanup; ignore malformed files
                continue
