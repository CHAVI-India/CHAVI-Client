"""
On-disk JSONL manifest service for per-file checkpoint tracking.

Each line in the manifest file is a JSON object: {"item_id": "...", "status": "done", "timestamp": "..."}.
On task resume, read_manifest() returns the set of already-completed item_ids
so the task can skip them.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings


def manifest_path_for_task(task_id, task_type=''):
    """Return the path to the JSONL manifest file for a given task."""
    manifest_dir = Path(settings.MEDIA_ROOT) / 'task_manifests'
    manifest_dir.mkdir(parents=True, exist_ok=True)
    return manifest_dir / f'{task_id}.jsonl'


def write_manifest_entry(manifest_path, item_id, status='done', payload=None):
    """Append a single entry to the manifest JSONL file.

    ``payload`` is an optional JSON-serializable dict stored with the entry so
    a resumed run can reconstruct per-item state (e.g. unmatched-row details)
    without reprocessing the item.
    """
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        'item_id': str(item_id),
        'status': status,
        'timestamp': datetime.utcnow().isoformat(),
    }
    if payload is not None:
        entry['payload'] = payload
    with open(manifest_path, 'a') as f:
        f.write(json.dumps(entry) + '\n')
        f.flush()
        os.fsync(f.fileno())


def read_manifest_entries(manifest_path):
    """Return {item_id: entry} for every entry in the manifest file.

    If an item_id appears more than once, the LAST entry wins (a redelivered
    run may re-record an item with a newer outcome). Returns an empty dict if
    the file does not exist.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return {}
    entries = {}
    with open(manifest_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries[entry['item_id']] = entry
            except (json.JSONDecodeError, KeyError):
                continue
    return entries


def read_manifest(manifest_path):
    """Return a set of completed item_ids from the manifest file.

    Returns an empty set if the file does not exist.
    """
    return {
        item_id
        for item_id, entry in read_manifest_entries(manifest_path).items()
        if entry.get('status') == 'done'
    }


def cleanup_manifest(manifest_path):
    """Delete the manifest file after successful completion."""
    manifest_path = Path(manifest_path)
    if manifest_path.exists():
        try:
            manifest_path.unlink()
        except OSError:
            pass
