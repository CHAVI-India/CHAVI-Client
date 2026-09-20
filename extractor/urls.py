from django.urls import path
from extractor import views

app_name = 'extractor'

urlpatterns = [
    path('wizard/start/', views.wizard_start, name='wizard_start'),
    path('wizard/start/refresh-schema/', views.wizard_start_refresh_schema, name='wizard_start_refresh_schema'),
    path('wizard/step1/', views.wizard_step1, name='wizard_step1'),
    path('wizard/step2/<int:response_model_id>/', views.wizard_step2, name='wizard_step2'),
    path('wizard/step3/<int:response_model_id>/', views.wizard_step3, name='wizard_step3'),
    path('wizard/step4/<int:response_model_id>/', views.wizard_step4, name='wizard_step4'),
    path('wizard/complete/<int:response_model_id>/', views.wizard_complete, name='wizard_complete'),
    
    path('response-models/', views.response_model_list, name='response_model_list'),
    path('response-models/<int:response_model_id>/', views.response_model_detail, name='response_model_detail'),
    path('response-models/<int:response_model_id>/messages/create/', views.instructor_message_create, name='instructor_message_create'),
    path('messages/<int:message_id>/edit/', views.instructor_message_edit, name='instructor_message_edit'),
    path('messages/<int:message_id>/delete/', views.instructor_message_delete, name='instructor_message_delete'),
    
    path('client-configurations/', views.client_configuration_list, name='client_configuration_list'),
    path('client-configurations/create/', views.client_configuration_create, name='client_configuration_create'),
    path('client-configurations/<int:config_id>/', views.client_configuration_detail, name='client_configuration_detail'),
    path('client-configurations/<int:config_id>/edit/', views.client_configuration_edit, name='client_configuration_edit'),
    path('client-configurations/<int:config_id>/delete/', views.client_configuration_delete, name='client_configuration_delete'),
    path('client-configurations/<int:config_id>/test-connection/', views.client_configuration_test_connection, name='client_configuration_test_connection'),
    
    path('files/', views.file_upload_list, name='file_upload_list'),
    path('files/upload/', views.file_upload_create, name='file_upload_create'),
    path('files/<int:file_id>/', views.file_upload_detail, name='file_upload_detail'),
    path('files/<int:file_id>/process/', views.file_upload_process, name='file_upload_process'),
    path('files/<int:file_id>/delete/', views.file_upload_delete, name='file_upload_delete'),
    path('processed/<int:processed_id>/', views.processed_text_view, name='processed_text_view'),
    path('processed/<int:processed_text_id>/ocr/', views.processed_text_ocr, name='processed_text_ocr'),
    
    path('extraction/', views.extraction_dashboard, name='extraction_dashboard'),
    path('extraction/patient/<int:patient_pk>/', views.patient_data, name='patient_data'),
    path('extraction/start/', views.extraction_start, name='extraction_start'),
    path('extraction/results/', views.extraction_results_list, name='extraction_results_list'),
    path('extraction/results/<int:job_id>/', views.extraction_job_detail, name='extraction_job_detail'),
    path('extraction/results/<int:result_id>/update/', views.extraction_result_update, name='extraction_result_update'),
    path('extraction/record/<int:extracted_record_id>/create/', views.extraction_record_create, name='extraction_record_create'),
    
    path('semantic-search/', views.semantic_search_settings, name='semantic_search_settings'),
    path('semantic-search/config/create/', views.embedding_config_create, name='embedding_config_create'),
    path('semantic-search/config/<int:config_id>/edit/', views.embedding_config_edit, name='embedding_config_edit'),
    path('semantic-search/config/<int:config_id>/delete/', views.embedding_config_delete, name='embedding_config_delete'),
    path('semantic-search/config/<int:config_id>/activate/', views.embedding_config_activate, name='embedding_config_activate'),
    path('semantic-search/compute/', views.compute_embeddings, name='compute_embeddings'),
    path('semantic-search/progress/<str:task_id>/', views.get_embedding_progress, name='get_embedding_progress'),
    
    path('api/tables/<int:table_id>/fields/', views.api_get_table_fields, name='api_get_table_fields'),
]
