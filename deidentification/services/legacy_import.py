import logging
import sqlite3
import os
from typing import Optional

logger = logging.getLogger(__name__)


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


def import_legacy_mappings(db_path: str, key_path: str, progress_callback=None) -> dict:
    from client_app.models import Patient, DICOMStudy, DICOMSeries, DICOMInstance
    from deidentification.models import DeidPatient, DeidStudy, DeidSeries, DeidInstance

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Legacy DB not found: {db_path}")
    if not os.path.exists(key_path):
        raise FileNotFoundError(f"Encryption key not found: {key_path}")

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

    stats = {
        'patients': 0, 'studies': 0, 'series': 0, 'instances': 0,
        'unmatched': 0,
        'unmatched_rows': [],
    }
    _progress_counter = [0]  # mutable counter for closure

    def _tick(label):
        _progress_counter[0] += 1
        if progress_callback:
            progress_callback(_progress_counter[0], total_rows, label)

    cursor.execute("SELECT * FROM patients")
    for row in cursor.fetchall():
        try:
            original_patient_id = _decrypt_value(row['encrypted_patient_id'], key)
            deidentified_patient_id = row['deidentified_patient_id']
            deid_dob = row['deidentified_date_of_birth']
            date_shift = int(_decrypt_value(row['encrypted_date_shift_value'], key))

            patient = Patient.objects.filter(patient_id=original_patient_id).first()
            if not patient:
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'patient',
                    'original_id': original_patient_id,
                    'deidentified_id': deidentified_patient_id,
                    'date_of_birth': deid_dob,
                    'date_shift': date_shift,
                })
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
            _tick(f"Imported patient {original_patient_id}")
        except Exception as e:
            logger.error(f"Failed to import legacy patient row: {e}")
            stats['unmatched'] += 1
            _tick(f"Failed patient row")

    cursor.execute("SELECT * FROM dicom_studies")
    for row in cursor.fetchall():
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
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'study',
                    'original_id': original_study_uid,
                    'deidentified_id': deid_study_uid,
                    'deidentified_date': deid_study_date,
                    'parent_patient_id': parent_patient_id,
                })
                _tick(f"Unmatched study {original_study_uid[:40]}")
                continue

            deid_patient = DeidPatient.objects.filter(patient=study.patient).first()
            if not deid_patient:
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'study',
                    'original_id': original_study_uid,
                    'deidentified_id': deid_study_uid,
                    'deidentified_date': deid_study_date,
                    'parent_patient_id': parent_patient_id,
                    'reason': 'parent patient not yet deidentified',
                })
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
            _tick(f"Imported study {original_study_uid[:40]}")
        except Exception as e:
            logger.error(f"Failed to import legacy study row: {e}")
            stats['unmatched'] += 1
            _tick("Failed study row")

    cursor.execute("SELECT * FROM dicom_series")
    for row in cursor.fetchall():
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
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'series',
                    'original_id': original_series_uid,
                    'deidentified_id': deid_series_uid,
                    'deidentified_series_date': deid_series_date,
                    'deidentified_frame_of_reference_uid': deid_frame_uid,
                    'parent_study_uid': parent_study_uid,
                })
                _tick(f"Unmatched series {original_series_uid[:40]}")
                continue

            deid_study = DeidStudy.objects.filter(study=series.study).first()
            if not deid_study:
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'series',
                    'original_id': original_series_uid,
                    'deidentified_id': deid_series_uid,
                    'deidentified_series_date': deid_series_date,
                    'deidentified_frame_of_reference_uid': deid_frame_uid,
                    'parent_study_uid': parent_study_uid,
                    'reason': 'parent study not yet deidentified',
                })
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
            _tick(f"Imported series {original_series_uid[:40]}")
        except Exception as e:
            logger.error(f"Failed to import legacy series row: {e}")
            stats['unmatched'] += 1
            _tick("Failed series row")

    cursor.execute("SELECT * FROM dicom_instances")
    for row in cursor.fetchall():
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
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'instance',
                    'original_id': original_sop_uid,
                    'deidentified_id': deid_sop_uid,
                    'parent_series_uid': parent_series_uid,
                })
                _tick(f"Unmatched instance {original_sop_uid[:40]}")
                continue

            deid_series = DeidSeries.objects.filter(series=instance.series).first()
            if not deid_series:
                stats['unmatched'] += 1
                stats['unmatched_rows'].append({
                    'type': 'instance',
                    'original_id': original_sop_uid,
                    'deidentified_id': deid_sop_uid,
                    'parent_series_uid': parent_series_uid,
                    'reason': 'parent series not yet deidentified',
                })
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
            _tick(f"Imported instance {original_sop_uid[:40]}")
        except Exception as e:
            logger.error(f"Failed to import legacy instance row: {e}")
            stats['unmatched'] += 1
            _tick("Failed instance row")

    conn.close()
    logger.info(f"Legacy import complete: {stats}")
    return stats
