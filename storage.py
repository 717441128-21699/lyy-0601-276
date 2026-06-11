from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from models import Contract, ContractDatabase


DEFAULT_DATA_FILE = ".contract_data.json"


def get_data_path(base_path: Optional[str] = None) -> str:
    if base_path:
        return os.path.join(base_path, DEFAULT_DATA_FILE)
    return DEFAULT_DATA_FILE


def save_contracts(contracts: List[Contract], base_path: Optional[str] = None) -> None:
    data = ContractDatabase(
        contracts=contracts,
        last_scan_time=datetime.now().isoformat(),
    )
    data_path = get_data_path(base_path)
    with open(data_path, "w", encoding="utf-8") as f:
        f.write(data.model_dump_json(indent=2, ensure_ascii=False))


def load_contracts(base_path: Optional[str] = None) -> List[Contract]:
    data_path = get_data_path(base_path)
    if not os.path.exists(data_path):
        return []
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    db = ContractDatabase.model_validate(data)
    return db.contracts


def get_scan_time(base_path: Optional[str] = None) -> Optional[str]:
    data_path = get_data_path(base_path)
    if not os.path.exists(data_path):
        return None
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("last_scan_time")
