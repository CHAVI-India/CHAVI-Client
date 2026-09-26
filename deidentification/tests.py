from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

HF_RECOGNIZER = (
    "presidio_analyzer.predefined_recognizers.ner."
    "huggingface_ner_recognizer.HuggingFaceNerRecognizer"
)


class AnalyzerEngineBuildTests(SimpleTestCase):
    """Engine construction for the pixel-scrub analyzer."""

    def _recognizer_names(self, analyzer):
        return [r.name for r in analyzer.registry.recognizers]

    @override_settings(DEID_PIXEL_NER_BACKEND="none")
    def test_none_backend_has_no_hf_recognizer(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        analyzer = _build_analyzer_engine()
        names = self._recognizer_names(analyzer)
        self.assertNotIn("HuggingFaceNerRecognizer", names)
        self.assertIn("LenientAadhaarRecognizer", names)
        self.assertIn("IndianMobileRecognizer", names)

    @override_settings(DEID_PIXEL_NER_BACKEND="hf")
    def test_hf_backend_registers_recognizer(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        with patch(f"{HF_RECOGNIZER}.load"):
            analyzer = _build_analyzer_engine()
        self.assertIn("HuggingFaceNerRecognizer", self._recognizer_names(analyzer))

    @override_settings(DEID_PIXEL_NER_BACKEND="hf")
    def test_hf_load_failure_degrades_to_spacy(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        with patch(f"{HF_RECOGNIZER}.load", side_effect=RuntimeError("boom")):
            analyzer = _build_analyzer_engine()
        self.assertNotIn(
            "HuggingFaceNerRecognizer", self._recognizer_names(analyzer)
        )

    @override_settings(DEID_PIXEL_NER_BACKEND="hf", DEID_LENIENT_INDIAN_IDS=False)
    def test_lenient_ids_can_be_disabled(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import (
            _build_analyzer_engine,
        )

        with patch(f"{HF_RECOGNIZER}.load"):
            analyzer = _build_analyzer_engine()
        names = self._recognizer_names(analyzer)
        self.assertNotIn("LenientAadhaarRecognizer", names)


class LabelMapTests(SimpleTestCase):
    def test_label_map_covers_ai4privacy_labels(self):
        from django.conf import settings

        model_labels = {
            "FIRSTNAME", "MIDDLENAME", "LASTNAME", "PREFIX",
            "CITY", "STATE", "COUNTY", "STREET", "BUILDINGNUMBER",
            "SECONDARYADDRESS", "ZIPCODE", "NEARBYGPSCOORDINATE",
            "ORDINALDIRECTION", "DATE", "DOB", "TIME", "AGE",
            "PHONENUMBER", "PHONEIMEI", "EMAIL", "URL",
            "IP", "IPV4", "IPV6", "MAC", "SSN", "ACCOUNTNUMBER",
            "PIN", "MASKEDNUMBER", "IBAN", "BIC", "CREDITCARDNUMBER",
            "CREDITCARDCVV", "CREDITCARDISSUER", "BITCOINADDRESS",
            "LITECOINADDRESS", "ETHEREUMADDRESS", "VEHICLEVIN",
            "VEHICLEVRM", "COMPANYNAME", "JOBTITLE", "JOBAREA", "JOBTYPE",
            "GENDER", "SEX", "HEIGHT", "EYECOLOR", "PASSWORD",
            "USERAGENT", "USERNAME", "ACCOUNTNAME", "AMOUNT", "CURRENCY",
            "CURRENCYCODE", "CURRENCYNAME", "CURRENCYSYMBOL",
        }
        self.assertTrue(
            model_labels.issubset(set(settings.DEID_HF_LABEL_MAP.keys()))
        )


class IndianIdRecognizerTests(SimpleTestCase):
    def _recognizer(self, name):
        from deidentification.utils.indian_id_recognizers import (
            build_indian_id_recognizers,
        )

        return {r.name: r for r in build_indian_id_recognizers()}[name]

    def test_lenient_aadhaar_matches_ocr_text(self):
        recognizer = self._recognizer("LenientAadhaarRecognizer")
        results = recognizer.analyze(
            "AADHAAR 1234 5678 9012", entities=["IN_AADHAAR"]
        )
        self.assertTrue(
            any(r.entity_type == "IN_AADHAAR" for r in results)
        )

    def test_indian_mobile_matches(self):
        recognizer = self._recognizer("IndianMobileRecognizer")
        results = recognizer.analyze(
            "PH +91 98765 43210", entities=["PHONE_NUMBER"]
        )
        self.assertTrue(
            any(r.entity_type == "PHONE_NUMBER" for r in results)
        )


class CaseNormalizingOcrTests(SimpleTestCase):
    def _fake_ocr_result(self):
        return {
            "text": ["NAME", "RAMESH", "KUMAR", "", "  ", "45Y"],
            "left": [0, 0, 0, 0, 0, 0],
            "top": [0, 0, 0, 0, 0, 0],
            "width": [10, 10, 10, 10, 10, 10],
            "height": [10, 10, 10, 10, 10, 10],
            "conf": [90, 90, 90, -1, -1, 90],
        }

    @override_settings(DEID_PIXEL_NORMALIZE_CASE=True)
    def test_words_title_cased_and_length_preserved(self):
        from deidentification.utils.burnt_in_pixel_scrubbing import _get_ocr

        with patch(
            "presidio_image_redactor.tesseract_ocr.pytesseract.image_to_data",
            return_value=self._fake_ocr_result(),
        ):
            ocr = _get_ocr()
            result = ocr.perform_ocr(None)

        self.assertEqual(
            result["text"], ["Name", "Ramesh", "Kumar", "", "  ", "45Y"]
        )

    @override_settings(DEID_PIXEL_NORMALIZE_CASE=False)
    def test_plain_tesseract_when_disabled(self):
        from presidio_image_redactor import TesseractOCR

        from deidentification.utils.burnt_in_pixel_scrubbing import _get_ocr

        ocr = _get_ocr()
        self.assertIs(type(ocr), TesseractOCR)
