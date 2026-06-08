import instructor
from openai import OpenAI
from pydantic import BaseModel, create_model
from typing import Any, Dict, List, Optional
from datetime import datetime
from logging import getLogger
from django.utils import timezone

from extractor.models import (
    ExtractionJob, ExtractionResult, ResponseModel, ProcessedText,
    ResponseModelTable, ResponseModelTableField, ExtractionStatusChoices,
    InstructorMessage
)
from extractor.services.pydantic_builder import PydanticModelBuilder
from extractor.services.semantic_search import SemanticSearchService

log = getLogger(__name__)


class InstructorExtractionService:
    """
    Service to handle data extraction using Instructor library with LLMs.
    """
    
    @staticmethod
    def get_instructor_client(response_model: ResponseModel, mode=None):
        """
        Create and return an Instructor-patched client based on the provider.
        
        Args:
            response_model: The ResponseModel configuration
            mode: Instructor mode (e.g., instructor.Mode.JSON for models without tool support)
        """
        client_config = response_model.client
        provider = client_config.model_provider.lower()
        
        if 'openai' in provider or 'azure' in provider or 'ollama' in provider or 'local' in provider:
            base_url = client_config.model_base_url.rstrip('/')
            if not base_url.startswith(('http://', 'https://')):
                base_url = f'http://{base_url}'
            
            # For Ollama, adjust the endpoint
            if 'ollama' in provider or 'local' in provider:
                if not base_url.endswith('/v1'):
                    base_url = f"{base_url}/v1"
                
                # Ollama doesn't need API key
                openai_client = OpenAI(
                    base_url=base_url,
                    api_key="ollama"  # Dummy key for Ollama
                )
            else:
                openai_client = OpenAI(
                    base_url=base_url if 'v1' in base_url else f"{base_url}/v1/chat/completions",
                    api_key=client_config.model_api_key
                )
            
            # Apply mode if specified
            if mode:
                return instructor.from_openai(openai_client, mode=mode)
            return instructor.from_openai(openai_client)
        
        elif 'anthropic' in provider:
            try:
                from anthropic import Anthropic
                anthropic_client = Anthropic(api_key=client_config.model_api_key)
                return instructor.from_anthropic(anthropic_client)
            except ImportError:
                raise ImportError(
                    "Anthropic library is not installed. "
                    "Install it with: pip install anthropic"
                )
        
        else:
            # Default to OpenAI-compatible
            base_url = client_config.model_base_url.rstrip('/')
            if not base_url.startswith(('http://', 'https://')):
                base_url = f'http://{base_url}'
            
            openai_client = OpenAI(
                base_url=base_url,
                api_key=client_config.model_api_key
            )
            return instructor.from_openai(openai_client)
    
    @staticmethod
    def build_dynamic_pydantic_model(response_model: ResponseModel) -> type[BaseModel]:
        """
        Build a Pydantic model dynamically from the ResponseModel configuration.
        """
        # Get all tables and fields
        model_tables = ResponseModelTable.objects.filter(
            response_model=response_model
        ).select_related('database_table__clientapp_content_type')
        
        fields_dict = {}
        
        for model_table in model_tables:
            table_fields = ResponseModelTableField.objects.filter(
                response_model_table=model_table
            ).select_related('field').order_by('order')
            
            for table_field in table_fields:
                field = table_field.field
                field_name = field.clientapp_field_name
                
                # Map field types to Python types
                field_type_map = {
                    'str': str,
                    'bool': bool,
                    'float': float,
                    'int': int,
                    'dict': dict,
                    'list': list,
                    'datetime.date': str,  # We'll use string for dates
                    'datetime.datetime': str,
                    'datetime.time': str,
                    'datetime.timedelta': str,
                }
                
                python_type = field_type_map.get(field.field_type, str)
                
                # Make field optional
                fields_dict[field_name] = (Optional[python_type], None)
        
        # Create the dynamic model
        DynamicModel = create_model(
            f'{response_model.name.replace(" ", "")}Model',
            **fields_dict
        )
        
        return DynamicModel
    
    @staticmethod
    def get_messages(response_model: ResponseModel, processed_content: str) -> List[Dict[str, str]]:
        """
        Build the messages array for the LLM from InstructorMessage and processed content.
        Includes field schema information for better extraction context.
        """
        messages = []
        
        # Get configured messages
        instructor_messages = InstructorMessage.objects.filter(
            response_model=response_model
        ).order_by('created_at')
        
        for msg in instructor_messages:
            # prompt is stored as JSON, could be a string or dict
            if isinstance(msg.prompt, dict):
                content = msg.prompt.get('content', str(msg.prompt))
            else:
                content = str(msg.prompt)
            
            messages.append({
                'role': msg.role,
                'content': content
            })
        
        # Build field schema information with document context for semantic search
        field_schema = InstructorExtractionService.build_field_schema_description(
            response_model,
            processed_content
        )
        
        # Add the user message with field schema and processed content
        user_content = f"""Extract the following fields from the document:

{field_schema}

EXTRACTION RULES:
1. For fields with "Valid Options" listed, you MUST match the extracted text to one of the provided options
2. Find the closest matching option from the list - use semantic similarity, not exact text match
3. Return the matched option label exactly as shown in the list
4. If the extracted text doesn't match any option well, return null
5. For regular fields without options, extract the exact text from the document

Document content:
{processed_content}"""
        
        messages.append({
            'role': 'user',
            'content': user_content
        })
        
        return messages
    
    @staticmethod
    def build_field_schema_description(response_model: ResponseModel, document_content: str = "") -> str:
        """
        Build a human-readable description of the fields to extract.
        Uses semantic search to show only relevant lookup options based on document context.
        """
        model_tables = ResponseModelTable.objects.filter(
            response_model=response_model
        ).select_related('database_table__clientapp_content_type')
        
        schema_parts = []
        
        for model_table in model_tables:
            table_name = model_table.database_table.clientapp_content_type.model
            table_fields = ResponseModelTableField.objects.filter(
                response_model_table=model_table
            ).select_related('field', 'field__lookup_content_type').order_by('order')
            
            if table_fields.exists():
                schema_parts.append(f"\n{table_name.upper()} Fields:")
                for table_field in table_fields:
                    field = table_field.field
                    field_info = f"  - {field.clientapp_field_name} ({field.get_field_type_display()})"
                    
                    # Add lookup information using semantic search
                    if field.lookup_field and field.lookup_content_type:
                        lookup_model = field.lookup_content_type.model_class()
                        
                        # Use semantic search to get relevant options
                        if document_content:
                            filtered_options = SemanticSearchService.get_filtered_lookup_options(
                                lookup_model,
                                field.lookup_table_pk_field_name,
                                field.lookup_table_value_field_name,
                                document_content
                            )
                        else:
                            # Fallback to all options if no document context
                            filtered_options = InstructorExtractionService.get_lookup_options(
                                lookup_model,
                                field.lookup_table_pk_field_name,
                                field.lookup_table_value_field_name
                            )[:10]  # Limit to 10
                        
                        if filtered_options:
                            labels = [opt['label'] for opt in filtered_options]
                            field_info += f"\n    Valid Options (most relevant): {', '.join(labels)}"
                            field_info += f"\n    IMPORTANT: Match the extracted text to the CLOSEST option from this list."
                            field_info += f"\n    Return ONLY the matched option label. If no good match, return null."
                        else:
                            field_info += f"\n    Lookup Table: {field.lookup_content_type.model}"
                            field_info += f"\n    Extract the exact text from the document."
                    
                    schema_parts.append(field_info)
        
        return "\n".join(schema_parts) if schema_parts else "No fields configured"
    
    @staticmethod
    def map_label_to_code(lookup_model, pk_field_name: str, value_field_name: str, extracted_label: str) -> Optional[str]:
        """
        Map an extracted label back to its lookup code.
        
        Args:
            lookup_model: The Django model class for the lookup table
            pk_field_name: The field name containing the primary key/code
            value_field_name: The field name containing the display label
            extracted_label: The label extracted by the LLM
        
        Returns:
            The corresponding code, or None if not found
        """
        try:
            if not lookup_model or not pk_field_name or not value_field_name or not extracted_label:
                return None
            
            # Try exact match first (case-insensitive)
            result = lookup_model.objects.filter(
                **{f"{value_field_name}__iexact": extracted_label}
            ).values_list(pk_field_name, flat=True).first()
            
            if result:
                return str(result)
            
            # Try partial match if exact match fails
            result = lookup_model.objects.filter(
                **{f"{value_field_name}__icontains": extracted_label}
            ).values_list(pk_field_name, flat=True).first()
            
            if result:
                log.warning(f"Partial match for '{extracted_label}': {result}")
                return str(result)
            
            log.warning(f"No lookup code found for label: '{extracted_label}'")
            return None
            
        except Exception as e:
            log.error(f"Error mapping label to code: {e}")
            return None
    
    @staticmethod
    def get_lookup_options(lookup_model, pk_field_name: str, value_field_name: str) -> List[Dict[str, str]]:
        """
        Fetch all possible options from a lookup table with both code and label.
        
        Args:
            lookup_model: The Django model class for the lookup table
            pk_field_name: The field name containing the primary key/code
            value_field_name: The field name containing the display label/value to show to LLM
        
        Returns:
            List of dicts with 'code' and 'label' keys
        """
        try:
            if not lookup_model or not pk_field_name or not value_field_name:
                return []
            
            # Get all label-code pairs from the lookup table
            # Note: value_field_name is the LABEL (what we show), pk_field_name is the CODE (what we store)
            options = lookup_model.objects.values_list(value_field_name, pk_field_name)
            
            # Convert to list of dicts, filtering out None/empty values
            result = []
            for label, code in options:
                if label and code:
                    result.append({
                        'label': str(label),  # Human-readable label for LLM to match
                        'code': str(code)     # Code to store in database
                    })
            
            return result
            
        except Exception as e:
            log.warning(f"Could not fetch lookup options from {lookup_model}: {e}")
            return []
    
    @staticmethod
    def extract_data(
        extraction_job: ExtractionJob,
        processed_content: str,
        user
    ) -> Dict[str, Any]:
        """
        Perform the actual data extraction using Instructor.
        
        Returns:
            Dict with 'success', 'data', 'tokens_used', 'raw_response', 'error'
        """
        try:
            # Update job status
            extraction_job.extraction_status = ExtractionStatusChoices.PROCESSING
            extraction_job.extraction_start_datetime = timezone.now()
            extraction_job.save()
            
            response_model = extraction_job.response_model
            
            # Determine mode based on provider
            # Ollama models often don't support function calling, use JSON mode
            provider = response_model.client.model_provider.lower()
            mode = None
            if 'ollama' in provider:
                log.info("Using JSON mode for Ollama model (no tool support)")
                mode = instructor.Mode.JSON
            
            # Get Instructor client with appropriate mode
            client = InstructorExtractionService.get_instructor_client(response_model, mode=mode)
            
            # Build Pydantic model
            PydanticModel = InstructorExtractionService.build_dynamic_pydantic_model(response_model)
            
            # Get messages
            messages = InstructorExtractionService.get_messages(response_model, processed_content)
            
            log.info(f"Starting extraction with model: {response_model.client.llm_model_name}")
            log.info(f"Messages: {messages}")
            
            # Call Instructor
            result = client.chat.completions.create(
                model=response_model.client.llm_model_name,
                response_model=PydanticModel,
                messages=messages,
                max_tokens=4096,
            )
            
            # Extract data
            extracted_data = result.model_dump()
            
            log.info(f"Extraction completed. Data: {extracted_data}")
            
            # Update job
            extraction_job.extraction_status = ExtractionStatusChoices.COMPLETED
            extraction_job.extraction_end_datetime = timezone.now()
            extraction_job.raw_llm_response = extracted_data
            extraction_job.tokens_used = None  # Instructor doesn't always provide token count
            extraction_job.save()
            
            # Save extraction results
            InstructorExtractionService.save_extraction_results(
                extraction_job,
                extracted_data,
                user
            )
            
            return {
                'success': True,
                'data': extracted_data,
                'tokens_used': extraction_job.tokens_used,
                'raw_response': extracted_data,
                'error': None
            }
            
        except Exception as e:
            log.error(f"Extraction failed: {e}", exc_info=True)
            
            # Update job with error
            extraction_job.extraction_status = ExtractionStatusChoices.FAILED
            extraction_job.extraction_end_datetime = timezone.now()
            extraction_job.extraction_error = str(e)
            extraction_job.save()
            
            return {
                'success': False,
                'data': None,
                'tokens_used': None,
                'raw_response': None,
                'error': str(e)
            }
    
    @staticmethod
    def save_extraction_results(
        extraction_job: ExtractionJob,
        extracted_data: Dict[str, Any],
        user
    ):
        """
        Save the extracted data as ExtractionResult records.
        For lookup fields, maps the extracted label to its code and stores both.
        """
        response_model = extraction_job.response_model
        
        # Get all fields from the response model
        model_tables = ResponseModelTable.objects.filter(
            response_model=response_model
        )
        
        for model_table in model_tables:
            table_fields = ResponseModelTableField.objects.filter(
                response_model_table=model_table
            ).select_related('field', 'field__lookup_content_type')
            
            for table_field in table_fields:
                field = table_field.field
                field_name = field.clientapp_field_name
                
                # Get the extracted value (this is the label for lookup fields)
                extracted_label = extracted_data.get(field_name)
                
                if extracted_label is not None:
                    # For lookup fields, map label to code
                    if field.lookup_field and field.lookup_content_type:
                        lookup_code = InstructorExtractionService.map_label_to_code(
                            field.lookup_content_type.model_class(),
                            field.lookup_table_pk_field_name,
                            field.lookup_table_value_field_name,
                            str(extracted_label)
                        )
                        
                        # Store as JSON with both label and code
                        stored_value = {
                            'label': str(extracted_label),
                            'code': lookup_code
                        }
                        data_to_store = str(stored_value)  # Convert dict to string for storage
                        
                        log.info(f"Mapped lookup field {field_name}: '{extracted_label}' -> code '{lookup_code}'")
                    else:
                        # Regular field, store as-is
                        data_to_store = str(extracted_label)
                    
                    # Create ExtractionResult
                    ExtractionResult.objects.create(
                        extraction_job=extraction_job,
                        database_field=field,
                        extracted_data=data_to_store,
                        verified_by=user,
                        data_accuracy='accurate'  # Default, can be changed later
                    )
                    
                    log.info(f"Saved extraction result for field: {field_name} = {data_to_store}")
    
    @staticmethod
    def bulk_extract(
        processed_files: List[ProcessedText],
        response_model: ResponseModel,
        user
    ) -> Dict[str, Any]:
        """
        Perform bulk extraction on multiple processed files.
        
        Returns:
            Dict with 'total', 'successful', 'failed', 'jobs'
        """
        from extractor.services.file_processor import FileProcessorService
        
        results = {
            'total': len(processed_files),
            'successful': 0,
            'failed': 0,
            'jobs': []
        }
        
        for processed_file in processed_files:
            try:
                # Create extraction job
                extraction_job = ExtractionJob.objects.create(
                    response_model=response_model,
                    processed_file=processed_file,
                    extracted_by=user,
                    extraction_status=ExtractionStatusChoices.PENDING
                )
                
                # Get processed content
                content = FileProcessorService.get_processed_content(processed_file)
                
                # Extract data
                result = InstructorExtractionService.extract_data(
                    extraction_job,
                    content,
                    user
                )
                
                if result['success']:
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                
                results['jobs'].append({
                    'job': extraction_job,
                    'result': result
                })
                
            except Exception as e:
                log.error(f"Bulk extraction failed for file {processed_file.id}: {e}")
                results['failed'] += 1
        
        return results
