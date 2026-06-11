from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from models import Contract, ContractDatabase, RuleConfig, ScanBatch
from scanner import ScanResult


DEFAULT_DATA_FILE = ".contract_data.json"
DEFAULT_RULE_FILE = ".rule_config.json"


def get_data_path(base_path: Optional[str] = None) -> str:
    if base_path:
        return os.path.join(base_path, DEFAULT_DATA_FILE)
    return DEFAULT_DATA_FILE


def get_rule_path(base_path: Optional[str] = None) -> str:
    if base_path:
        return os.path.join(base_path, DEFAULT_RULE_FILE)
    return DEFAULT_RULE_FILE


def generate_batch_id() -> str:
    return datetime.now().strftime("batch_%Y%m%d_%H%M%S_%f")[:-3]


def save_database(db: ContractDatabase, base_path: Optional[str] = None) -> None:
    data_path = get_data_path(base_path)
    with open(data_path, "w", encoding="utf-8") as f:
        f.write(db.model_dump_json(indent=2, ensure_ascii=False))


def load_database(base_path: Optional[str] = None) -> ContractDatabase:
    data_path = get_data_path(base_path)
    if not os.path.exists(data_path):
        return ContractDatabase()
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ContractDatabase.model_validate(data)


def save_contracts(contracts: List[Contract], base_path: Optional[str] = None) -> None:
    db = load_database(base_path)
    db.contracts = contracts
    db.last_scan_time = datetime.now().isoformat()
    save_database(db, base_path)


def load_contracts(base_path: Optional[str] = None) -> List[Contract]:
    db = load_database(base_path)
    return db.contracts


def get_scan_time(base_path: Optional[str] = None) -> Optional[str]:
    db = load_database(base_path)
    return db.last_scan_time


def save_rule(rule: RuleConfig, base_path: Optional[str] = None) -> None:
    rule_path = get_rule_path(base_path)
    with open(rule_path, "w", encoding="utf-8") as f:
        f.write(rule.model_dump_json(indent=2, ensure_ascii=False))
    db = load_database(base_path)
    db.current_rule = rule
    save_database(db, base_path)


def load_rule(base_path: Optional[str] = None) -> RuleConfig:
    rule_path = get_rule_path(base_path)
    if os.path.exists(rule_path):
        with open(rule_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return RuleConfig.model_validate(data)

    db = load_database(base_path)
    if db.current_rule:
        return db.current_rule

    return RuleConfig()


def add_batch(
    scan_result: ScanResult,
    folder: str,
    rule: RuleConfig,
    base_path: Optional[str] = None,
) -> str:
    db = load_database(base_path)
    batch_id = generate_batch_id()
    now = datetime.now().isoformat()

    existing_map = {c.file_path: c for c in db.contracts}

    all_contracts = scan_result.all_contracts
    for contract in all_contracts:
        contract.scan_batch_id = batch_id
        contract.last_scan_time = now
        if not contract.first_scan_time:
            contract.first_scan_time = now

        if contract.file_path in existing_map:
            old = existing_map[contract.file_path]
            if not contract.review_notes:
                contract.review_notes = old.review_notes

    file_path_set = {c.file_path for c in all_contracts}
    remaining = [c for c in db.contracts if c.file_path not in file_path_set]
    final_contracts = all_contracts + remaining

    batch = ScanBatch(
        batch_id=batch_id,
        scan_time=now,
        folder=folder,
        total_count=scan_result.total_count,
        new_count=scan_result.new_count,
        updated_count=scan_result.updated_count,
        unchanged_count=scan_result.unchanged_count,
        rule_name=rule.rule_name,
        contract_file_paths=[c.file_path for c in scan_result.all_contracts],
    )

    db.batches.insert(0, batch)
    db.contracts = final_contracts
    db.last_scan_time = now
    db.current_rule = rule

    save_database(db, base_path)
    return batch_id


def get_batches(base_path: Optional[str] = None) -> List[ScanBatch]:
    db = load_database(base_path)
    return db.batches


def get_contracts_by_batch(batch_id: str, base_path: Optional[str] = None) -> List[Contract]:
    db = load_database(base_path)
    batch = db.get_batch_by_id(batch_id)
    if not batch:
        return []
    path_set = set(batch.contract_file_paths)
    return [c for c in db.contracts if c.file_path in path_set]


def update_contract(contract: Contract, base_path: Optional[str] = None) -> None:
    db = load_database(base_path)
    for i, c in enumerate(db.contracts):
        if c.file_path == contract.file_path:
            db.contracts[i] = contract
            break
    save_database(db, base_path)


def update_contracts(updated_contracts: List[Contract], base_path: Optional[str] = None) -> None:
    db = load_database(base_path)
    update_map = {c.file_path: c for c in updated_contracts}
    for i, c in enumerate(db.contracts):
        if c.file_path in update_map:
            db.contracts[i] = update_map[c.file_path]
    for c in updated_contracts:
        if c.file_path not in {x.file_path for x in db.contracts}:
            db.contracts.append(c)
    save_database(db, base_path)
