"""
Views for the data import wizard.
"""
from .step1_upload import Step1UploadView
from .step2_auto_match import Step2AutoMatchView
from .step3_manual_match import Step3ManualMatchView
from .step4_mapping_review import Step4MappingReviewView
from .step5_validation import Step5ValidationView
from .step6_lookup_matching import Step6LookupMatchingView
from .step7_uuid_mapping import Step7UUIDMappingView
from .step8_import import Step8ImportView

__all__ = [
    'Step1UploadView',
    'Step2AutoMatchView',
    'Step3ManualMatchView',
    'Step4MappingReviewView',
    'Step5ValidationView',
    'Step6LookupMatchingView',
    'Step7UUIDMappingView',
    'Step8ImportView',
]
