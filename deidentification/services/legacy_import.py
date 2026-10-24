import logging
import sqlite3
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Cap on unmatched rows stored in the task result summary. Bounds the JSON
# column and memory on very large legacy DBs; the full count is still reported
# via ``unmatched_total``.
UNMATCHED_ROWS_CAP = 5000

# Rows fetched per iteration when streaming the legacy SQLite tables (avoids
# loading every table into memory at once).
_FETCH_BATCH = 500

# item_id prefix -> stats counter key.
_TYPE_STAT_KEY = {
    'patient': 'patients',
    'study': 'studies',
    'series': 'series',
    'instance': 'instances',
}


def _read_encryption_key(key_path: str) -> bytes:
    with open(key_path, 'rb') as f:
        return f.read()


def _decrypt_value(encrypted_value: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend

    import base64
    raw = base64.b64decode(encrypted_value)
    iv = raw[:16]
    ciphertext = raw[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode('utf-8')


def _seed_stats_from_entries(completed_entries) -> dict:
    """Rebuild the stats counters (and unmatched rows) from manifest entries
    written by a previous, interrupted run, so a resumed run reports the same
    final summary as an uninterrupted one.

    ``completed_entries`` maps item_id -> manifest entry (see
    ``client_app.services.task_checkpoint.read_manifest_entries``).
    """
    stats = {
        'patients': 0, 'studies': 0, 'series': 0, 'instances': 0,
        'unmatched': 0,
        'unmatched_rows': [],
        'unmatched_total': 0,
    }
    for item_id, entry in (completed_entries or {}).items():
        rtype = item_id.split(':', 1)[0]
        stat_key = _TYPE_STAT_KEY.get(rtype)
        status = entry.get('status')
        if status == 'done' and stat_key:
            stats[stat_key] += 1
        elif status == 'unmatched':
            stats['unmatched'] += 1
            stats['unmatched_total'] += 1
            payload = entry.get('payload')
            if payload and len(stats['unmatched_rows']) < UNMATCHED_ROWS_CAP:
                stats['unmatched_rows'].append(payload)
        elif status == 'error':
            # Row-level failures were counted as unmatched in the original
            # (non-checkpointed) implementation; keep that accounting.
            stats['unmatched'] += 1
            stats['unmatched_total'] += 1
    return stats


def import_legacy_mappings(db_path: str, key_path: str, progress_callback=None,
                           completed_entries=None, manifest_write_callback=None) -> dict:
    """Import legacy deidentification mappings into the client_app models.

    Checkpointing:
      * ``completed_entries`` maps item_id -> manifest entry from a previous
        (interrupted) run. Rows whose item_id is present are skipped, so a
        resumed run continues from the last checkpointed row.
      * ``manifest_write_callback(item_id, status, payload)`` is invoked after
        each row is processed so the caller can persist the checkpoint.
        ``status`` is one of ``done`` / ``unmatched`` / ``error``.

    Item ids are keyed on the legacy row's SQLite ``rowid`` (stable for the
    lifetime of the uploaded file) so checkpointing works even for rows that
    fail to decrypt.
    """
    from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
    from deidentification.models import DeidPatient, DeidStudy, DeidSeries, DeidInstance

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Legacy DB not found: {db_path}")
    if not os.path.exists(key_path):
        raise FileNotFoundError(f"Encryption key not found: {key_path}")

    completed_entries = dict(completed_entries or {})

    def _checkpoint(item_id, status='done', payload=None):
        if item_id in completed_entries:
            return
        entry = {'item_id': item_id, 'status': status}
        if payload is not None:
            entry['payload'] = payload
        completed_entries[item_id] = entry
        if manifest_write_callback:
            manifest_write_callback(item_id, status, payload)

    key = _read_encryption_key(key_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Count total rows across all tables for progress tracking
    cursor.execute("SELECT COUNT(*) AS cnt FROM patients")
    total_patients = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) AS cnt FROM dicom_studies")
    total_studies = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) AS cnt FROM dicom_series")
    total_series = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) AS cnt FROM dicom_instances")
    total_instances = cursor.fetchone()['cnt']
    total_rows = total_patients + total_studies + total_series + total_instances

    stats = _seed_stats_from_entries(completed_entries)

    def _record_unmatched(payload):
        stats['unmatched'] += 1
        stats['unmatched_total'] += 1
        if len(stats['unmatched_rows']) < UNMATCHED_ROWS_CAP:
            stats['unmatched_rows'].append(payload)

    # Rows already checkpointed by a previous run count toward progress.
    _progress_counter = [len(completed_entries)]

    def _tick(label):
        _progress_counter[0] += 1
        if progress_callback:
            progress_callback(_progress_counter[0], total_rows, label)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    cursor.execute("SELECT rowid AS _rowid, * FROM patients")
    while True:
        rows = cursor.fetchmany(_FETCH_BATCH)
        if not rows:
            break
        for row in rows:
            item_id = f"patient:{row['_rowid']}"
            if item_id in completed_entries:
                _tick("Skipping completed patient row")
                continue
            try:
                original_patient_id = _decrypt_value(row['encrypted_patient_id'], key)
                deidentified_patient_id = row['deidentified_patient_id']
                deid_dob = row['deidentified_date_of_birth']
                date_shift = int(_decrypt_value(row['encrypted_date_shift_value'], key))

                patient = Patient.objects.filter(patient_id=original_patient_id).first()
                if not patient:
                    payload = {
                        'type': 'patient',
                        'original_id': original_patient_id,
                        'deidentified_id': deidentified_patient_id,
                        'date_of_birth': deid_dob,
                        'date_shift': date_shift,
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    logger.warning(f"Legacy patient {original_patient_id} not found in client_app — skipping")
                    _tick(f"Unmatched patient {original_patient_id}")
                    continue

                DeidPatient.objects.update_or_create(
                    patient=patient,
                    defaults={
                        'deidentified_patient_id': deidentified_patient_id,
                        'date_shift_value': date_shift,
                        'deidentified_date_of_birth': deid_dob,
                    },
                )
                stats['patients'] += 1
                _checkpoint(item_id, 'done')
                _tick(f"Imported patient {original_patient_id}")
            except Exception as e:
                logger.error(f"Failed to import legacy patient row: {e}")
                stats['unmatched'] += 1
                stats['unmatched_total'] += 1
                _checkpoint(item_id, 'error', {'type': 'patient', 'error': str(e)})
                _tick("Failed patient row")

    # ------------------------------------------------------------------
    # Studies
    # ------------------------------------------------------------------
    cursor.execute("SELECT rowid AS _rowid, * FROM dicom_studies")
    while True:
        rows = cursor.fetchmany(_FETCH_BATCH)
        if not rows:
            break
        for row in rows:
            item_id = f"study:{row['_rowid']}"
            if item_id in completed_entries:
                _tick("Skipping completed study row")
                continue
            try:
                original_study_uid = _decrypt_value(row['encrypted_study_uid'], key)
                deid_study_uid = row['deidentified_study_uid']
                deid_study_date = row['deidentified_study_date']

                # Try to get parent patient ID from legacy DB
                parent_patient_id = ''
                try:
                    parent_patient_id = _decrypt_value(row['encrypted_patient_id'], key)
                except (KeyError, IndexError, TypeError):
                    pass

                study = DICOMStudy.objects.filter(study_instance_uid=original_study_uid).first()
                if not study:
                    payload = {
                        'type': 'study',
                        'original_id': original_study_uid,
                        'deidentified_id': deid_study_uid,
                        'deidentified_date': deid_study_date,
                        'parent_patient_id': parent_patient_id,
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    _tick(f"Unmatched study {original_study_uid[:40]}")
                    continue

                deid_patient = DeidPatient.objects.filter(patient=study.patient).first()
                if not deid_patient:
                    payload = {
                        'type': 'study',
                        'original_id': original_study_uid,
                        'deidentified_id': deid_study_uid,
                        'deidentified_date': deid_study_date,
                        'parent_patient_id': parent_patient_id,
                        'reason': 'parent patient not yet deidentified',
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    _tick(f"Unmatched study {original_study_uid[:40]}")
                    continue

                DeidStudy.objects.update_or_create(
                    study=study,
                    defaults={
                        'deid_patient': deid_patient,
                        'deidentified_study_instance_uid': deid_study_uid,
                        'deidentified_study_date': deid_study_date,
                    },
                )
                stats['studies'] += 1
                _checkpoint(item_id, 'done')
                _tick(f"Imported study {original_study_uid[:40]}")
            except Exception as e:
                logger.error(f"Failed to import legacy study row: {e}")
                stats['unmatched'] += 1
                stats['unmatched_total'] += 1
                _checkpoint(item_id, 'error', {'type': 'study', 'error': str(e)})
                _tick("Failed study row")

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------
    cursor.execute("SELECT rowid AS _rowid, * FROM dicom_series")
    while True:
        rows = cursor.fetchmany(_FETCH_BATCH)
        if not rows:
            break
        for row in rows:
            item_id = f"series:{row['_rowid']}"
            if item_id in completed_entries:
                _tick("Skipping completed series row")
                continue
            try:
                original_series_uid = _decrypt_value(row['encrypted_series_uid'], key)
                deid_series_uid = row['deidentified_series_uid']
                deid_series_date = row['deidentified_series_date']
                deid_frame_uid = row['deidentified_frame_of_reference_uid']

                # Try to get parent study UID from legacy DB
                parent_study_uid = ''
                try:
                    parent_study_uid = _decrypt_value(row['encrypted_study_uid'], key)
                except (KeyError, IndexError, TypeError):
                    pass

                series = DICOMSeries.objects.filter(series_instance_uid=original_series_uid).first()
                if not series:
                    payload = {
                        'type': 'series',
                        'original_id': original_series_uid,
                        'deidentified_id': deid_series_uid,
                        'deidentified_series_date': deid_series_date,
                        'deidentified_frame_of_reference_uid': deid_frame_uid,
                        'parent_study_uid': parent_study_uid,
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    _tick(f"Unmatched series {original_series_uid[:40]}")
                    continue

                deid_study = DeidStudy.objects.filter(study=series.study).first()
                if not deid_study:
                    payload = {
                        'type': 'series',
                        'original_id': original_series_uid,
                        'deidentified_id': deid_series_uid,
                        'deidentified_series_date': deid_series_date,
                        'deidentified_frame_of_reference_uid': deid_frame_uid,
                        'parent_study_uid': parent_study_uid,
                        'reason': 'parent study not yet deidentified',
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    _tick(f"Unmatched series {original_series_uid[:40]}")
                    continue

                DeidSeries.objects.update_or_create(
                    series=series,
                    defaults={
                        'deid_study': deid_study,
                        'deidentified_series_instance_uid': deid_series_uid,
                        'deidentified_series_date': deid_series_date,
                        'deidentified_frame_of_reference_uid': deid_frame_uid,
                    },
                )
                stats['series'] += 1
                _checkpoint(item_id, 'done')
                _tick(f"Imported series {original_series_uid[:40]}")
            except Exception as e:
                logger.error(f"Failed to import legacy series row: {e}")
                stats['unmatched'] += 1
                stats['unmatched_total'] += 1
                _checkpoint(item_id, 'error', {'type': 'series', 'error': str(e)})
                _tick("Failed series row")

    # ------------------------------------------------------------------
    # Instances
    # ------------------------------------------------------------------
    cursor.execute("SELECT rowid AS _rowid, * FROM dicom_instances")
    while True:
        rows = cursor.fetchmany(_FETCH_BATCH)
        if not rows:
            break
        for row in rows:
            item_id = f"instance:{row['_rowid']}"
            if item_id in completed_entries:
                _tick("Skipping completed instance row")
                continue
            try:
                original_sop_uid = _decrypt_value(row['encrypted_sop_instance_uid'], key)
                deid_sop_uid = row['deidentified_sop_instance_uid']

                # Try to get parent series UID from legacy DB
                parent_series_uid = ''
                try:
                    parent_series_uid = _decrypt_value(row['encrypted_series_uid'], key)
                except (KeyError, IndexError, TypeError):
                    pass

                instance = DICOMInstance.objects.filter(sop_instance_uid=original_sop_uid).first()
                if not instance:
                    payload = {
                        'type': 'instance',
                        'original_id': original_sop_uid,
                        'deidentified_id': deid_sop_uid,
                        'parent_series_uid': parent_series_uid,
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    _tick(f"Unmatched instance {original_sop_uid[:40]}")
                    continue

                deid_series = DeidSeries.objects.filter(series=instance.series).first()
                if not deid_series:
                    payload = {
                        'type': 'instance',
                        'original_id': original_sop_uid,
                        'deidentified_id': deid_sop_uid,
                        'parent_series_uid': parent_series_uid,
                        'reason': 'parent series not yet deidentified',
                    }
                    _record_unmatched(payload)
                    _checkpoint(item_id, 'unmatched', payload)
                    _tick(f"Unmatched instance {original_sop_uid[:40]}")
                    continue

                DeidInstance.objects.update_or_create(
                    instance=instance,
                    defaults={
                        'deid_series': deid_series,
                        'deidentified_sop_instance_uid': deid_sop_uid,
                    },
                )
                stats['instances'] += 1
                _checkpoint(item_id, 'done')
                _tick(f"Imported instance {original_sop_uid[:40]}")
            except Exception as e:
                logger.error(f"Failed to import legacy instance row: {e}")
                stats['unmatched'] += 1
                stats['unmatched_total'] += 1
                _checkpoint(item_id, 'error', {'type': 'instance', 'error': str(e)})
                _tick("Failed instance row")

    conn.close()
    logger.info(f"Legacy import complete: {stats}")
    return stats
