# Step 7 Duration Date - Improvements Needed

## Issues Identified

1. **Single mapping only** - Should support multiple duration-to-date calculations
2. **Reference date widget** - Doesn't show CSV columns dropdown or date picker based on type
3. **Target date fields** - Limited to unmapped fields, should show ALL date fields from selected models

## Required Changes

### View Changes (`step7_duration_date.py`)

1. Change `all_date_fields` to include ALL date fields (not just unmapped)
2. Pass CSV headers, duration units, reference date types, and date formats to template as JSON
3. Handle multiple mappings in POST (format: `duration_0_csv_field`, `duration_1_csv_field`, etc.)

### Template Changes (`step7_duration_date.html`)

1. Add JavaScript to dynamically add/remove duration mappings
2. Reference date widget should change based on type:
   - `CSV_COLUMN` → Dropdown with CSV headers
   - `CUSTOM` → Date picker input
3. Show all date fields in target dropdown
4. Better help text with example

### Key Code Snippets

**View - Get ALL date fields:**
```python
all_date_fields = []
for model_name in selected_models:
    date_fields = FieldIntrospectionService.get_date_fields(model_name)
    for field in date_fields:
        all_date_fields.append(f"{model_name}.{field}")
```

**Template - Dynamic reference widget:**
```javascript
function updateReferenceInput(index, refType) {
    if (refType === 'CUSTOM') {
        // Show date picker
        html = '<input type="date" ...>';
    } else {
        // Show CSV column dropdown
        html = '<select>...</select>';
    }
}
```

## Status
⚠️ **NEEDS IMPLEMENTATION** - Too complex for single response, requires careful testing
