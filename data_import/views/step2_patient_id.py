"""
Step 2: Map patient ID column and check existence.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from .base import BaseImportView
from ..forms import Step2PatientIDMappingForm
from ..models import FilePatientID, FileImportSessionStep
from client_app.models import Patient


class Step2PatientIDMappingView(BaseImportView):
    """
    Step 2: Map patient ID column from CSV and check which patients exist.
    """
    step_identifier = FileImportSessionStep.PATIENT_ID
    step_name = "Map Patient ID Column"
    template_name = 'data_import/step2_patient_id.html'
    
    def get(self, request, session_id):
        """
        Display the patient ID mapping form.
        """
        session = self.get_session(session_id)
        
        # Validate step access
        if not self.validate_step_access(session):
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Get CSV headers
        headers, rows, error = self.get_csv_data(session)
        
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        # Check if patient IDs already mapped
        existing_mappings = FilePatientID.objects.filter(file_import_session=session)
        
        if existing_mappings.exists() and session.patient_id_column:
            # Show existing mappings with pre-selected column
            patient_ids = list(existing_mappings.values_list('patient_id', 'exists_in_client_app_database'))
            selected_column = session.patient_id_column
            
            # Pre-populate form with previously selected column
            form = Step2PatientIDMappingForm(
                csv_headers=headers,
                initial={'patient_id_column': session.patient_id_column}
            )
        else:
            form = Step2PatientIDMappingForm(csv_headers=headers)
            patient_ids = None
            selected_column = None
        
        # Calculate counts for display
        existing_count = 0
        new_count = 0
        if patient_ids:
            existing_count = sum(1 for _, exists in patient_ids if exists)
            new_count = len(patient_ids) - existing_count
        
        context = self.get_context_data(
            session=session,
            form=form,
            headers=headers,
            patient_ids=patient_ids,
            selected_column=selected_column,
            existing_count=existing_count,
            new_count=new_count,
        )
        
        return render(request, self.template_name, context)
    
    def post(self, request, session_id):
        """
        Handle patient ID column selection and check existence.
        """
        session = self.get_session(session_id)
        
        # Get CSV data
        headers, rows, error = self.get_csv_data(session)
        
        if error:
            messages.error(request, f"Error reading CSV: {error}")
            return redirect('data_import:step1_edit', session_id=session.id)
        
        form = Step2PatientIDMappingForm(csv_headers=headers, data=request.POST)
        
        if form.is_valid():
            patient_id_column = form.cleaned_data['patient_id_column']
            
            # Save patient_id_column to session
            session.patient_id_column = patient_id_column
            session.save()
            
            # Get unique patient IDs from CSV
            from ..services import CSVProcessorService
            unique_patient_ids = CSVProcessorService.get_unique_values(rows, patient_id_column, headers)
            
            if not unique_patient_ids:
                messages.error(request, f"No patient IDs found in column '{patient_id_column}'")
                context = self.get_context_data(session=session, form=form, headers=headers)
                return render(request, self.template_name, context)
            
            # Clear existing mappings
            FilePatientID.objects.filter(file_import_session=session).delete()
            
            # Check which patient IDs exist in database
            existing_patients = set(
                Patient.objects.filter(patient_id__in=unique_patient_ids)
                .values_list('patient_id', flat=True)
            )
            
            # Create FilePatientID records
            patient_id_objects = []
            for patient_id in unique_patient_ids:
                exists = patient_id in existing_patients
                patient_id_objects.append(
                    FilePatientID(
                        file_import_session=session,
                        patient_id=patient_id,
                        exists_in_client_app_database=exists
                    )
                )
            
            # Bulk create
            FilePatientID.objects.bulk_create(patient_id_objects)
            
            # Update session step
            self.update_session_step(session, FileImportSessionStep.MODEL_SELECTION)
            
            # Show summary
            new_patients = len(unique_patient_ids) - len(existing_patients)
            messages.success(
                request,
                f"Patient ID mapping completed. Found {len(unique_patient_ids)} unique patient IDs."
            )
            
            # Redirect to Step 3
            return redirect('data_import:step3', session_id=session.id)
        
        # Form is invalid
        context = self.get_context_data(
            session=session,
            form=form,
            headers=headers,
        )
        return render(request, self.template_name, context)
