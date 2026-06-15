"""
Management command to fix lookup_table_value_field_name from 'code' to 'label' or 'description'.
"""

from django.core.management.base import BaseCommand
from extractor.models import DatabaseField


class Command(BaseCommand):
    help = 'Fix lookup_table_value_field_name to use label/description instead of code'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Find all lookup fields with value_field = 'code'
        wrong_fields = DatabaseField.objects.filter(
            lookup_field=True,
            lookup_table_value_field_name='code'
        )
        
        total = wrong_fields.count()
        
        if total == 0:
            self.stdout.write(self.style.SUCCESS('No fields need fixing!'))
            return
        
        self.stdout.write(f'\nFound {total} fields with incorrect value field configuration')
        self.stdout.write('=' * 80)
        
        # Check what field name exists in each lookup table
        field_mapping = {}
        
        for field in wrong_fields:
            if not field.lookup_content_type:
                continue
            
            lookup_model = field.lookup_content_type.model_class()
            if not lookup_model:
                continue
            
            # Get field names from the model
            model_fields = [f.name for f in lookup_model._meta.get_fields()]
            
            # Determine the correct value field
            if 'label' in model_fields:
                correct_field = 'label'
            elif 'description' in model_fields:
                correct_field = 'description'
            elif 'name' in model_fields:
                correct_field = 'name'
            else:
                correct_field = None
            
            field_mapping[field.id] = {
                'field': field,
                'lookup_table': field.lookup_content_type.model,
                'current': field.lookup_table_value_field_name,
                'correct': correct_field,
                'model_fields': model_fields
            }
        
        # Display changes
        updated_count = 0
        skipped_count = 0
        
        for field_id, info in field_mapping.items():
            field = info['field']
            correct_field = info['correct']
            
            if correct_field:
                self.stdout.write(
                    f"\n✓ {field.clientapp_field_name} ({info['lookup_table']})"
                )
                self.stdout.write(f"  Current: {info['current']}")
                self.stdout.write(self.style.SUCCESS(f"  Will change to: {correct_field}"))
                
                if not dry_run:
                    field.lookup_table_value_field_name = correct_field
                    field.save(update_fields=['lookup_table_value_field_name'])
                    updated_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n✗ {field.clientapp_field_name} ({info['lookup_table']})"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"  Could not determine correct field. Available: {info['model_fields']}"
                    )
                )
                skipped_count += 1
        
        self.stdout.write('\n' + '=' * 80)
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDRY RUN: Would update {len([v for v in field_mapping.values() if v["correct"]])} fields'
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f'Run without --dry-run to apply changes'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✓ Updated {updated_count} fields successfully!'
                )
            )
            if skipped_count > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'✗ Skipped {skipped_count} fields (manual review needed)'
                    )
                )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nNext step: Run "python manage.py compute_lookup_embeddings --refresh" to recompute embeddings'
                )
            )
