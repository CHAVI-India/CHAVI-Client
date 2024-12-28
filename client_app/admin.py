from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(Center)
admin.site.register(Patient)
admin.site.register(Project)
admin.site.register(PatientProject)
admin.site.register(LookupFMACode)
admin.site.register(Diagnosis)