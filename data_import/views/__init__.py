"""
Views for the data import wizard.
"""
from .step1_upload import Step1UploadView
from .step2_field_mapping import Step2FieldMappingView
from .step3_date_format_config import Step3DateFormatConfigView
from .step4_date_interval_config import Step4DateIntervalConfigView
from .step5_validation import Step5ValidationView
from .step6_lookup_matching import Step6LookupMatchingView
from .step7_static_mapping import Step7StaticMappingView
from .step8_uuid_mapping import Step8UUIDMappingView
from .step9_import import Step9ImportView
from .step10_execute import Step10ExecuteView

__all__ = [
    'Step1UploadView',
    'Step2FieldMappingView',
    'Step3DateFormatConfigView',
    'Step4DateIntervalConfigView',
    'Step5ValidationView',
    'Step6LookupMatchingView',
    'Step7StaticMappingView',
    'Step8UUIDMappingView',
    'Step9ImportView',
    'Step10ExecuteView',
]
