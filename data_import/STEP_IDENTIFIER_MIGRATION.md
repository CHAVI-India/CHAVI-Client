# Step Identifier Migration Guide

## Changes Required

All step views need to be updated from `step_number` to `step_identifier`.

### Pattern to Replace

**OLD:**
```python
step_number = X
self.update_session_step(session, X+1)
```

**NEW:**
```python
step_identifier = FileImportSessionStep.XXXXX
self.update_session_step(session, FileImportSessionStep.XXXXX)
```

### Step-by-Step Updates

#### Step 3 - Model Selection
```python
# OLD
step_number = 3
self.update_session_step(session, 4)

# NEW
step_identifier = FileImportSessionStep.MODEL_SELECTION
self.update_session_step(session, FileImportSessionStep.FIELD_MAPPING)
```

#### Step 4 - Field Mapping
```python
# OLD
step_number = 4
self.update_session_step(session, 5)

# NEW
step_identifier = FileImportSessionStep.FIELD_MAPPING
self.update_session_step(session, FileImportSessionStep.COLUMN_VALUE)
```

#### Step 5 - Column Value
```python
# OLD
step_number = 5
self.update_session_step(session, 6)

# NEW
step_identifier = FileImportSessionStep.COLUMN_VALUE
self.update_session_step(session, FileImportSessionStep.DATE_FORMAT)
```

#### Step 6 - Date Format
```python
# OLD
step_number = 6
self.update_session_step(session, 7)

# NEW
step_identifier = FileImportSessionStep.DATE_FORMAT
self.update_session_step(session, FileImportSessionStep.DURATION_DATE)
```

#### Step 7 - Duration Date
```python
# OLD
step_number = 7
self.update_session_step(session, 8)

# NEW
step_identifier = FileImportSessionStep.DURATION_DATE
self.update_session_step(session, FileImportSessionStep.LOOKUP_MAPPING)
```

#### Step 8 - Lookup Mapping
```python
# OLD
step_number = 8
self.update_session_step(session, 9)

# NEW
step_identifier = FileImportSessionStep.LOOKUP_MAPPING
self.update_session_step(session, FileImportSessionStep.MISSING_RELATIONS)
```

#### Step 9 - Missing Relations
```python
# OLD
step_number = 9
self.update_session_step(session, 10)

# NEW
step_identifier = FileImportSessionStep.MISSING_RELATIONS
self.update_session_step(session, FileImportSessionStep.REVIEW)
```

#### Step 10 - Review
```python
# OLD
step_number = 10
self.update_session_step(session, 11)

# NEW
step_identifier = FileImportSessionStep.REVIEW
self.update_session_step(session, FileImportSessionStep.EXECUTE)
```

#### Step 11 - Execute
```python
# OLD
step_number = 11

# NEW
step_identifier = FileImportSessionStep.EXECUTE
```

### Files to Update

1. `/views/step3_model_selection.py`
2. `/views/step4_field_mapping.py`
3. `/views/step5_column_value.py`
4. `/views/step6_date_format.py`
5. `/views/step7_duration_date.py`
6. `/views/step8_lookup_mapping.py`
7. `/views/step9_missing_relations.py`
8. `/views/step10_review.py`
9. `/views/step11_execute.py`

### After Updates

1. Run migrations:
```bash
python manage.py makemigrations data_import
python manage.py migrate data_import
```

2. Test each step transition

3. Benefits:
   - Easy to add/remove steps
   - No number conflicts
   - Self-documenting code
   - Flexible ordering
