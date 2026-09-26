"""Text-specific Presidio recognizers for the extractor deidentification step.

The shared India bundle (built-in IN_* recognizers, lenient Aadhaar, Indian
mobile) is imported from deidentification.utils.indian_id_recognizers so the
pixel-scrub and text pipelines stay identical for those entities. Everything
here is text-only coverage: identifiers that appear in clinical notes, plus
gazetteer deny-lists that compensate for en_core_web_lg's weak recall on
Indian names and places.
"""

from pathlib import Path

from django.conf import settings
from presidio_analyzer import Pattern, PatternRecognizer

GAZETTEER_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_gazetteer(filename: str):
    path = Path(getattr(settings, 'EXTRACTOR_DEID_GAZETTEER_DIR', GAZETTEER_DIR)) / filename
    try:
        return [
            line.strip()
            for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.startswith('#')
        ]
    except OSError:
        return []


def build_text_recognizers():
    """Return the text-only custom recognizers for the deid analyzer.

    Patterns that could false-positive on ordinary clinical numbers carry a
    low base score (0.05) and depend on context words to cross the analyzer
    threshold; unambiguous formats score higher standalone.
    """
    recognizers = [
        # ABHA / Ayushman Bharat health account: 14 digits, often grouped 2-4-4-4
        PatternRecognizer(
            supported_entity="IN_ABHA",
            name="AbhaNumberRecognizer",
            patterns=[Pattern(
                "ABHA number (14-digit)",
                r"\b\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", 0.4)],
            context=["abha", "ayushman", "health id", "ndhm", "abdm"],
        ),
        # ABHA address handle: name@abdm / name@sbx
        PatternRecognizer(
            supported_entity="IN_ABHA",
            name="AbhaAddressRecognizer",
            patterns=[Pattern(
                "ABHA address",
                r"\b[a-zA-Z0-9.\-_]{2,}@(?:abdm|sbx)\b", 0.6)],
            context=["abha", "abdm", "health id"],
        ),
        # UPI handles look like emails; only fire with payment context
        PatternRecognizer(
            supported_entity="IN_UPI",
            name="UpiRecognizer",
            patterns=[Pattern(
                "UPI virtual payment address",
                r"\b[a-zA-Z0-9.\-_]{2,}@[a-zA-Z]{2,}\b", 0.05)],
            context=["upi", "vpa", "gpay", "paytm", "phonepe", "bhim"],
        ),
        # Indian PIN codes: 6 digits, leading digit 1-9. Bare pattern is too
        # noisy on clinical numbers — context-gated.
        PatternRecognizer(
            supported_entity="IN_PINCODE",
            name="IndianPinCodeRecognizer",
            patterns=[Pattern(
                "Indian PIN code",
                r"\b[1-9]\d{5}\b", 0.05)],
            context=["pin", "pincode", "pin code", "postal", "post"],
        ),
        # Indian driving licence: SS-RR-YYYY-NNNNNNN variants
        PatternRecognizer(
            supported_entity="IN_DRIVING_LICENSE",
            name="IndianDrivingLicenseRecognizer",
            patterns=[Pattern(
                "Indian driving licence",
                r"\b[A-Z]{2}[-\s]?\d{2}[-\s]?\d{4}[-\s]?\d{7}\b", 0.4)],
            context=["driving licence", "driving license", "dl no", "dl number"],
        ),
        # Hospital identifiers: MRN/UHID/registration numbers.
        PatternRecognizer(
            supported_entity="MEDICAL_RECORD_NUMBER",
            name="MedicalRecordNumberRecognizer",
            patterns=[
                # Prefixed segmented IDs: MR/26/092837, OP/26/093450,
                # AS/26/011111/040 — the letter-letter/digits/digits shape is
                # unambiguous on its own; near-certain score so NER's
                # short prefix tags (e.g. 'MR' as ORGANIZATION) can't
                # outvote it and leave the digits behind.
                Pattern(
                    "Prefixed segmented record number",
                    r"\b[A-Z]{2}/\d{2}/\d{4,}\b", 0.95),
                # Segmented identifiers: S-23-004512, MR-23-004512
                Pattern(
                    "Segmented record number",
                    r"\b[A-Z]{0,4}[-/.]?\d{1,6}[-/.]\d{2,10}\b", 0.05),
                Pattern(
                    "Medical record number",
                    r"\b[A-Z]{0,4}[-/.]?\d{4,10}\b", 0.05),
            ],
            context=[
                "mrn", "mr no", "medical record", "uhid", "reg no",
                "registration no", "hospital no", "patient id", "ip no",
                "op no", "opd no", "ipd no", "case no", "admission no",
                "histopathology", "histopath", "biopsy no", "lab no",
                "report no", "accession no", "slide no", "specimen no",
            ],
        ),
        # Title-prefixed names: Dr. Sharma, Smt. Lakshmi, S/o Kumar
        PatternRecognizer(
            supported_entity="PERSON",
            name="IndianTitleNameRecognizer",
            patterns=[Pattern(
                "Title + name",
                r"(?:Dr\.?|Sri|Shri|Smt\.?|Kum\.?|S/o|D/o|W/o)\s+"
                r"[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2}", 0.5)],
            context=["patient", "consultant", "ref", "referred", "by", "resident"],
        ),
        # Date catch-alls so every date-like surface is shifted, not just the
        # ones spaCy/HF recognize. Moderate score — formats are unambiguous.
        PatternRecognizer(
            supported_entity="DATE_TIME",
            name="DatePatternRecognizer",
            patterns=[
                Pattern(
                    "Numeric date DD/MM/YYYY variants",
                    r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b", 0.4),
                Pattern(
                    "Day-Month-Year with month name",
                    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
                    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
                    r"[,]?\s+\d{2,4}\b", 0.4),
                Pattern(
                    "Month-Day-Year with month name",
                    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
                    r"\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{2,4}\b", 0.4),
                Pattern(
                    "ISO date",
                    r"\b\d{4}-\d{2}-\d{2}\b", 0.4),
            ],
            context=["date", "dob", "born", "admission", "discharge", "on",
                     "dated", "visit", "follow up", "review"],
        ),
    ]

    names = _load_gazetteer('indian_names.txt')
    if names:
        # deny_list does word-boundary token matching; moderate score, boosted
        # by name context. False positives on everyday words are the price of
        # recall — review UI is the backstop.
        recognizers.append(PatternRecognizer(
            supported_entity="PERSON",
            name="IndianNameGazetteerRecognizer",
            deny_list=names,
            deny_list_score=0.35,
            context=[
                "patient", "name", "s/o", "w/o", "d/o", "shri", "smt",
                "mr", "mrs", "ms", "kumari", "master", "baby",
            ],
        ))

    locations = _load_gazetteer('indian_locations.txt')
    if locations:
        recognizers.append(PatternRecognizer(
            supported_entity="LOCATION",
            name="IndianLocationGazetteerRecognizer",
            deny_list=locations,
            deny_list_score=0.35,
            context=[
                "village", "taluk", "tehsil", "district", "dist", "state",
                "near", "r/o", "resident of", "address", "at", "from",
            ],
        ))

    recognizers.append(PatternRecognizer(
        supported_entity="IN_RELIGION",
        name="ReligionCasteRecognizer",
        deny_list=[
            "hindu", "muslim", "christian", "sikh", "jain", "buddhist",
            "parsi", "brahmin", "kshatriya", "vaishya", "shudra",
            "dalit", "scheduled caste", "scheduled tribe", "obc",
        ],
        deny_list_score=0.4,
        context=["religion", "caste", "community", "category"],
    ))

    return recognizers


def build_patient_recognizers(patient):
    """Ad-hoc recognizers for the linked patient's known identifiers.

    Guarantees the patient's own ID and DOB are caught even when NER misses
    them — cheap insurance since uploads are already linked to a Patient.
    Returns [] when no patient is linked.
    """
    if patient is None:
        return []

    recognizers = []
    patient_id = patient.patient_id
    if patient_id:
        canonical = ''.join(c for c in patient_id if c.isalnum()).upper()
        deny = {patient_id, canonical}
        recognizers.append(PatternRecognizer(
            supported_entity="PATIENT_ID",
            name="LinkedPatientIdRecognizer",
            deny_list=list(deny),
            deny_list_score=0.9,
        ))

    dob = getattr(patient, 'date_of_birth', None)
    if dob:
        variants = {
            dob.strftime('%d/%m/%Y'), dob.strftime('%d-%m-%Y'),
            dob.strftime('%Y-%m-%d'), dob.strftime('%d %b %Y'),
            dob.strftime('%d %B %Y'), dob.strftime('%Y%m%d'),
        }
        recognizers.append(PatternRecognizer(
            supported_entity="DATE_TIME",
            name="LinkedPatientDobRecognizer",
            deny_list=list(variants),
            deny_list_score=0.9,
        ))

    return recognizers
