"""India-specific recognizers for burnt-in pixel scrubbing.

Presidio ships country-specific India recognizers (Aadhaar, PAN, Voter ID,
passport, vehicle registration, GSTIN) but they are ``enabled: false`` in
``default_recognizers.yaml`` — the default registry never loads them, so we
instantiate them here. Additionally, the built-in ``InAadhaarRecognizer``
validates the Verhoeff checksum, which OCR-mangled digits almost never
satisfy, so a lenient Aadhaar recognizer (no checksum) is added on top.
Over-redaction is the safe direction for de-identification.
"""

from presidio_analyzer import Pattern, PatternRecognizer
from presidio_analyzer.predefined_recognizers.country_specific.india import (
    InAadhaarRecognizer,
    InGstinRecognizer,
    InPanRecognizer,
    InPassportRecognizer,
    InVehicleRegistrationRecognizer,
    InVoterRecognizer,
)


def build_indian_id_recognizers():
    """Return India-specific recognizers for the pixel-scrub analyzer."""
    recognizers = [
        # Built-in Presidio recognizers (disabled by default upstream).
        # InAadhaarRecognizer keeps its Verhoeff checksum — valid for
        # clean OCR; the lenient variant below covers noisy digits.
        InPanRecognizer(),
        InVoterRecognizer(),
        InPassportRecognizer(),
        InVehicleRegistrationRecognizer(),
        InGstinRecognizer(),
        InAadhaarRecognizer(),
    ]

    recognizers.append(
        PatternRecognizer(
            supported_entity="IN_AADHAAR",
            name="LenientAadhaarRecognizer",
            patterns=[
                Pattern(
                    "Aadhaar (lenient, no checksum)",
                    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
                    0.5,
                ),
            ],
            context=["aadhaar", "uid", "uidai", "aadhar"],
            supported_language="en",
        )
    )

    # phonenumbers-based PhoneRecognizer misses OCR-formatted Indian mobiles
    recognizers.append(
        PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            name="IndianMobileRecognizer",
            patterns=[
                Pattern(
                    "Indian mobile (+91 / 0 prefix / bare 10-digit)",
                    r"(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}\b",
                    0.4,
                ),
            ],
            context=["mob", "mobile", "ph", "phone", "contact", "tel"],
            supported_language="en",
        )
    )

    return recognizers
