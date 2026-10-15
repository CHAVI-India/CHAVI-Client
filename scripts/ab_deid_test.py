"""A/B evaluation: rule-based (Presidio + Stanford NER) vs local-LLM NER
deidentification on synthetic Indian clinical documents.

Usage:
    python scripts/ab_deid_test.py                 # run full A/B
    python scripts/ab_deid_test.py --clean         # remove rows created by prior runs

The script creates FileUpload/ProcessedText rows (named ab_deid_* so they
are identifiable) so the results can also be inspected on the normal
review pages.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')

import django  # noqa: E402

django.setup()

from pathlib import Path  # noqa: E402
from django.conf import settings  # noqa: E402
from django.core.files.base import ContentFile  # noqa: E402
from django.utils import timezone  # noqa: E402

from extractor.models import (  # noqa: E402
    ClientConfiguration, FileUpload, ProcessedText, BackgroundTask)
from extractor.services.text_deidentification import (  # noqa: E402
    TextDeidentificationService)
from extractor.services.file_processor import FileProcessorService  # noqa: E402

MODEL_NAME = 'gemma4:e2b'

# ---------------------------------------------------------------------------
# Synthetic documents — realistic Indian hospital records (breast-cancer
# workup: clinical note, radiology, histopathology). PII is deliberate and
# catalogued below for leak scanning.
# ---------------------------------------------------------------------------

DOC_CLINICAL = """DISCHARGE SUMMARY
KOLKATA MEDICAL INSTITUTE, Salt Lake, Kolkata - 700091

Patient: Mr. Rajesh Kumar S/o Late Bhaskar Kumar, Age 56 years, Sex: Male
Address: House No. 12/4B, Ghat Road, Village Patia, P.O. Mahishadal,
District West Medinipur, West Bengal - 716130
MR/26/092837  |  Mobile: +91 98312 45678  |  Aadhaar: 8412 3456 7890
Date of Admission: 01/02/2024    Date of Discharge: 06/02/2024

HISTORY OF PRESENTING COMPLAINTS:
The patient presented with progressive swelling in the left breast for 1
month, with skin dimpling noticed for 2 weeks. He had a fever for 3 days
prior to admission. Family history: mother died of breast cancer.

EXAMINATION:
Left breast lump 4 x 3.5 cm, hard, with skin tethering. Left axillary
lymph nodes: 3 matted nodes, largest 12 mm.

INVESTIGATIONS:
CEA 4.2 ng/mL, CA 15-3 380 IU/mL. FNAC: malignant cells.
Mammogram: EIBC. MRN: MR/26/092837

DIAGNOSIS: Left breast carcinoma
TREATMENT: Neoadjuvant chemotherapy (EC-T) for 4 cycles.
FOLLOW UP: advised in 1 month with CEA and mammogram.

Referring doctor: Dr. Meena Nair, Oncologist, Apollo Hospital, Kolkata.
Attending physician: Dr. Subhojit Das
"""

DOC_RADIOLOGY = """RADIOLOGY REPORT
KOLKATA MEDICAL INSTITUTE - Department of Diagnostic Radiology
Report No: RAD/26/004512
Patient: Rajesh Kumar            MRN: MR/26/092837
DOB: 12/04/1968                  Date of Exam: 04/02/2024
Referring Physician: Dr. Meena Nair

CLINICAL HISTORY: Carcinoma left breast on neoadjuvant chemotherapy.
Staging CT requested.

CT CHEST / ABDOMEN / PELVIS WITH CONTRAST
Technologist: Mr. Prasant Roy

FINDINGS:
Lungs: No pulmonary metastasis. Right upper lobe: 3 mm nonspecific nodule.
Lymph nodes: Subcarinal node 9 mm (short axis) - borderline.
Liver: No focal lesion. No ascites. Spleen normal.
Pelvis: No pelvic sidewall lymphadenopathy.

IMPRESSION:
No distant metastasis on CT chest, abdomen and pelvis.
Staging: cT2 N1 M0.
Repeat CT advised in 3 months.

Reported by: Dr. Anirban Ghosh, Senior Radiologist
Verified by: Dr. S. K. Bose, Consultant Radiologist
"""

DOC_PATHOLOGY = """HISTOPATHOLOGY REPORT
KOLKATA MEDICAL INSTITUTE - Department of Pathology
Accession No: HP/26/011111
Specimen: Left breast lump biopsy
Patient: Rajesh Kumar
MRN: MR/26/092837
Date of Reception: 02/02/2024    Date of Reporting: 05/02/2024
Referring: Dr. Subhojit Das

CLINICAL: Left breast lump 4 x 3.5 cm with skin involvement.

GROSS: Grey-white firm tissue 2.5 x 2 x 1.8 cm.
MICROSCOPY: Infiltrating ductal carcinoma, Grade III (Nottingham 8/9).
Lymphovascular invasion: present in 3 vessels per high power field.
Margins: closest margin 1.2 mm (inferior).
IMMUNOHISTOCHEMISTRY: ER negative, PR negative, HER2 3+ (overexpressed),
Ki-67 45%. p16 shows patchy nuclear expression. D2-40 highlights LVI.
Lymph nodes examined: 2/12 positive (left axillary).

DIAGNOSIS: Invasive ductal carcinoma, triple-positive, Grade III.
IHC: HER2 positive - suitable for targeted therapy.

Reported by: Dr. Ritu Mandal, Consultant Pathologist
"""

DOCS = [  # .csv exercises the CSV deid branch (no mapped headers -> whole-text)
    ('AB-SYNTH clinical note (discharge summary)', DOC_CLINICAL, '.csv'),
    ('AB-SYNTH radiology report (CT staging)', DOC_RADIOLOGY, '.csv'),
    ('AB-SYNTH pathology report (histopathology)', DOC_PATHOLOGY, '.csv'),
]

# PII tokens that must NOT survive deidentification.
PII_TOKENS = [
    'Rajesh Kumar', 'Bhaskar Kumar', 'Meena Nair', 'Subhojit Das',
    'Prasant Roy', 'Anirban Ghosh', 'S. K. Bose', 'Ritu Mandal',
    'Patia', 'Mahishadal', 'West Medinipur', 'Salt Lake', 'Ghat Road',
    'Kolkata',
    'MR/26/092837', 'RAD/26/004512', 'HP/26/011111',
    '8412 3456 7890', '841234567890',
    '98312 45678', '9831245678',
    '716130', '700091',
]

# Clinical content that MUST survive (over-redaction check).
CLINICAL_TOKENS = [
    '1 month', '2 weeks', '3 days', '3 months',
    'lymph nodes', 'p16', 'D2-40', 'Ki-67', 'HER2',
    '4 x 3.5', '12 mm', 'EC-T', 'triple-positive', 'Nottingham',
    'cT2 N1 M0',
]

# Dates (shifted, not removed — checked separately).
DATES = [
    '01/02/2024', '06/02/2024', '12/04/1968',
    '04/02/2024', '02/02/2024', '05/02/2024',
]


def get_or_create_config():
    cfg = ClientConfiguration.objects.filter(llm_model_name=MODEL_NAME).first()
    if cfg:
        cfg.enable_text_deid = True
        cfg.deid_local_certified = True
        cfg.save()
        return cfg
    return ClientConfiguration.objects.create(
        llm_model_name=MODEL_NAME,
        model_provider='Local (Ollama)',
        model_api_key='ollama',
        model_base_url='http://localhost:11434',
        request_timeout=300,
        context_size=131072,
        enable_text_deid=True,
        deid_local_certified=True,
        is_default_deid=False,
    )


def clean():
    n_files = FileUpload.objects.filter(
        original_filename__startswith='ab_deid_').count()
    FileUpload.objects.filter(
        original_filename__startswith='ab_deid_').delete()
    n_tasks = BackgroundTask.objects.filter(
        task_name__startswith='AB deid ').delete()[0]
    print(f'Cleaned {n_files} upload(s), {n_tasks} background task(s).')


def prepare(doc_name, content, ext):
    """One fresh FileUpload + ProcessedText row for the document."""
    stamp = timezone.now().strftime('%H%M%S')
    upload = FileUpload.objects.create(
        original_filename=f'ab_deid_{doc_name.split()[1]}_{stamp}{ext}',
        file=ContentFile(content.encode('utf-8'),
                         f'ab_deid_{stamp}{ext}'))
    pt = ProcessedText.objects.create(
        file_upload=upload,
        processed_file_path=f'uploads/ab_deid_src_{upload.id}{ext}',
        content_length=len(content),
    )
    path = Path(settings.MEDIA_ROOT) / pt.processed_file_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return pt


def run_engine(pt, label, backend, client_config_id):
    from extractor.models import BackgroundTask as BT
    task = BT.objects.create(
        task_id=f'abdeid-{pt.id}-{int(timezone.now().timestamp())}',
        task_name=f'AB deid {label} on PT {pt.id}',
        status='running',
    )
    started = time.monotonic()
    try:
        new = TextDeidentificationService.deidentify(
            pt, backend=backend, client_config_id=client_config_id)
        elapsed = time.monotonic() - started
        if new is None:
            task.mark_failed('skipped (already deidentified)')
            return None
        task.mark_complete({
            'version': new.version, 'engine': new.deid_engine,
            'entities': new.deid_entities, 'seconds': round(elapsed, 1)})
        out = FileProcessorService.get_processed_content(new)
        return {'row': new, 'content': out, 'seconds': round(elapsed, 1)}
    except Exception as e:
        elapsed = time.monotonic() - started
        task.mark_failed(str(e))
        print(f'  [{label}] FAILED after {elapsed:.1f}s: {e}')
        return None


def compare(doc_label, source, results):
    source_lower = source.lower()
    ppi = [t for t in PII_TOKENS if t.lower() in source_lower]
    clinical = [t for t in CLINICAL_TOKENS if t.lower() in source_lower]
    dates = [d for d in DATES if d in source]
    print(f'\n{"=" * 78}')
    print(f'{doc_label}')
    print(f'  (source contains {len(ppi)} PII tokens, '
          f'{len(clinical)} clinical tokens, {len(dates)} dates)')
    print('=' * 78)
    for label, res in results.items():
        if res is None:
            print(f'\n--- {label}: FAILED ---')
            continue
        new, out = res['row'], res['content']
        print(f'\n--- {label}  (engine={new.deid_engine}, '
              f'{res["seconds"]}s, v{new.version}) ---')
        counts = new.deid_entities or {}
        print('  entities: ' + ', '.join(
            f'{k}={v}' for k, v in sorted(counts.items())))
        leaks = [t for t in ppi
             if t.lower() in out.lower() or t in out]
        lost = [t for t in clinical if t.lower() not in out.lower()]
        dates_kept = [d for d in dates if d in out]
        print(f'  PII LEAKS ({len(leaks)}): '
              f'{leaks if leaks else "none"}')
        print(f'  over-redacted clinical terms ({len(lost)}): '
              f'{lost if lost else "none"}')
        print(f'  unshifted dates ({len(dates_kept)}): '
              f'{dates_kept if dates_kept else "none (all shifted)"}')


def rescan():
    """Re-scan existing ab_deid rows without re-running the engines."""
    from extractor.models import FileUpload
    uploads = list(FileUpload.objects.filter(
        original_filename__startswith='ab_deid_').order_by('id'))
    if not uploads:
        print('No ab_deid uploads found. Run without --rescan first.')
        return
    for upload in uploads:
        rows = list(ProcessedText.objects.filter(
            file_upload=upload).order_by('version'))
        source = next(r for r in rows if not r.deidentified)
        source_content = FileProcessorService.get_processed_content(source)
        source_lower = source_content.lower()
        ppi = [t for t in PII_TOKENS if t.lower() in source_lower]
        clinical = [t for t in CLINICAL_TOKENS if t.lower() in source_lower]
        dates = [d for d in DATES if d in source_content]
        print(f'\n{"=" * 78}')
        print(f'{upload.original_filename}  (source PT {source.id})')
        print(f'  source contains {len(ppi)} PII tokens, '
              f'{len(clinical)} clinical tokens, {len(dates)} dates')
        print('=' * 78)
        for r in rows:
            if not r.deidentified:
                continue
            out = FileProcessorService.get_processed_content(r)
            tag = f'{r.deid_engine} / {r.deid_model or "-"}'
            print(f'\n--- PT {r.id}  [{tag}]  shift={r.deid_date_shift_days}')
            counts = r.deid_entities or {}
            print('  entities: ' + ', '.join(
                f'{k}={v}' for k, v in sorted(counts.items())))
            leaks = [t for t in ppi if t.lower() in out.lower()]
            lost = [t for t in clinical if t.lower() not in out.lower()]
            kept = [d for d in dates if d in out]
            print(f'  PII leaks: {leaks if leaks else "none"}')
            print(f'  clinical lost: {lost if lost else "none"}')
            print(f'  unshifted dates: {kept if kept else "none"}')


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--llm-only', action='store_true')
    parser.add_argument('--rescan', action='store_true')
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    if args.rescan:
        rescan()
        return

    cfg = get_or_create_config()
    print(f'LLM config: {cfg.id} / {cfg.llm_model_name} '
          f'({cfg.model_base_url})')

    report = []
    for doc_name, content, ext in DOCS:
        print(f'\nPreparing: {doc_name} ({len(content)} chars)')
        # each engine needs its own source row
        pt_pres = prepare(doc_name, content, ext)
        pt_llm = prepare(doc_name, content, ext)
        results = {}
        if not args.llm_only:
            results['Presidio + Stanford'] = run_engine(
                pt_pres, 'presidio', 'presidio', None)
        results['LLM NER (gemma4:e2b)'] = run_engine(
            pt_llm, 'llm', 'llm', cfg.id)
        report.append((doc_name, results))
        compare(doc_name, content, results)

    print(f'\n{"=" * 78}')
    print('SUMMARY')
    print('=' * 78)
    for doc_name, results in report:
        source = next(c for n, c, _ in DOCS if n == doc_name)
        source_lower = source.lower()
        ppi = [t for t in PII_TOKENS if t.lower() in source_lower]
        clinical = [t for t in CLINICAL_TOKENS if t.lower() in source_lower]
        for label, res in results.items():
            if res is None:
                print(f'  {doc_name[:38]:40s} {label:28s} FAILED')
                continue
            out = res['content']
            leaks = [t for t in ppi if t.lower() in out.lower()]
            lost = [t for t in clinical if t.lower() not in out.lower()]
            print(f'  {doc_name[:38]:40s} {label:28s} '
                  f'leaks={len(leaks)} lost={len(lost)} '
                  f'{res["seconds"]}s  '
                  f'(deid row: {res["row"].id})')
    print('\nNote: review-page links above use the source row id; the')
    print('deidentified versions are linked from the file detail page.')


if __name__ == '__main__':
    main()
