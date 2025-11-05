#!/usr/bin/env python
"""Check date format configurations in database"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
django.setup()

from data_import.models import ImportData, ImportDateFormatConfiguration, DataFieldConfiguration

print("=" * 80)
print("CHECKING DATE FORMAT CONFIGURATIONS")
print("=" * 80)

# Check all imports
all_imports = ImportData.objects.all().order_by('-id')
print(f"\nTotal imports in database: {all_imports.count()}")
print("\nRecent imports:")
for imp in all_imports[:5]:
    print(f"  Import ID {imp.id}: {imp.import_data_title or 'Untitled'} - Status: {imp.status}")

# Check all date format configs
all_configs = ImportDateFormatConfiguration.objects.all()
print(f"\n\nTotal date format configs: {all_configs.count()}")

if all_configs.exists():
    print("\nDate format configurations:")
    for config in all_configs:
        print(f"  Config ID {config.id}:")
        print(f"    -> DataFieldConfig ID: {config.data_field_configuration.id}")
        print(f"    -> Import ID: {config.data_field_configuration.import_data.id}")
        print(f"    -> Field: {config.data_field_configuration.file_field_name}")
        print(f"    -> Format: {config.date_format}, Separator: {config.date_separator}")
        print()
else:
    print("  No date format configurations found!")

# Check specific import (19)
print("\n" + "=" * 80)
print("CHECKING IMPORT ID 19")
print("=" * 80)

try:
    import_19 = ImportData.objects.get(id=19)
    print(f"\nImport 19 exists: {import_19.import_data_title or 'Untitled'}")
    print(f"Status: {import_19.status}")
    print(f"Field mappings: {import_19.data_fields.count()}")
    
    # Check date format configs for import 19
    configs_for_19 = ImportDateFormatConfiguration.objects.filter(
        data_field_configuration__import_data=import_19
    )
    print(f"Date format configs for import 19: {configs_for_19.count()}")
    
    if configs_for_19.exists():
        print("\nConfigs for import 19:")
        for config in configs_for_19:
            print(f"  - {config.data_field_configuration.file_field_name}: {config.date_format}/{config.date_separator}")
    
    # Check which field mappings are date fields
    print(f"\n\nDate field mappings in import 19:")
    date_mappings = import_19.data_fields.filter(
        client_app_field_name__icontains='date'
    )
    print(f"Found {date_mappings.count()} mappings with 'date' in field name:")
    for mapping in date_mappings:
        has_config = ImportDateFormatConfiguration.objects.filter(
            data_field_configuration=mapping
        ).exists()
        print(f"  Mapping ID {mapping.id}: {mapping.file_field_name} -> {mapping.client_app_table_name}.{mapping.client_app_field_name}")
        print(f"    Has config: {has_config}")
    
except ImportData.DoesNotExist:
    print("\nImport 19 does not exist!")

print("\n" + "=" * 80)
