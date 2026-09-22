from django import forms


class ReviewApprovalForm(forms.Form):
    confirm = forms.BooleanField(required=True)
    acknowledge_duplicates = forms.BooleanField(required=False)


class ExtractionRecordReviewForm(forms.Form):
    def __init__(self, *, record, operation, instance=None, data=None, prefix=None):
        self.record = record
        self.operation = operation
        self.instance = instance
        self.database_fields = list(record.database_table.databasefield_set.filter(
            is_active=True).select_related('lookup_content_type'))
        fields = {f.clientapp_field_name: f for f in self.database_fields if f.is_extractable()}
        super().__init__(data=data, prefix=prefix)
        for db_field in fields.values():
            model_field = record.database_table.clientapp_content_type.model_class()._meta.get_field(
                db_field.clientapp_field_name)
            try:
                form_field = model_field.formfield()
            except Exception:
                form_field = forms.CharField(required=False)
            if form_field is None:
                continue
            form_field.required = False
            if db_field.lookup_field:
                form_field.widget = forms.Select()
                choices = [('', '---------')]
                if instance is not None:
                    current = getattr(instance, model_field.name, None)
                    if current is not None:
                        choices.append((str(current.pk), str(current)))
                form_field.choices = choices
            self.fields[db_field.clientapp_field_name] = form_field
