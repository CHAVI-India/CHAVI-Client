# Template Filters Fix - Jinja2 to Django Conversion

## Issue
Several templates used **Jinja2-specific filters** that don't exist in Django's template system, causing `TemplateSyntaxError`.

---

## Problems Found

### 1. **Step 2: `selectattr` and `rejectattr` filters**
```django
{{ patient_ids|selectattr:"1"|list|length }}  ❌ Jinja2 only
{{ patient_ids|rejectattr:"1"|list|length }}  ❌ Jinja2 only
```

### 2. **Steps 4, 6, 9: `get_item` filter**
```django
{{ models_fields|get_item:model_name }}  ❌ Doesn't exist in Django
{{ existing_formats_dict|get_item:csv_column }}  ❌ Doesn't exist in Django
```

---

## Solutions Applied

### **Solution 1: Calculate in View (Step 2)**
Instead of filtering in template, calculate counts in Python:

**View (`step2_patient_id.py`):**
```python
# Calculate counts for display
existing_count = 0
new_count = 0
if patient_ids:
    existing_count = sum(1 for _, exists in patient_ids if exists)
    new_count = len(patient_ids) - existing_count

context = self.get_context_data(
    ...
    existing_count=existing_count,
    new_count=new_count,
)
```

**Template (`step2_patient_id.html`):**
```django
<div class="text-2xl font-bold text-green-600">{{ existing_count }}</div>
<div class="text-2xl font-bold text-blue-600">{{ new_count }}</div>
```

---

### **Solution 2: Custom Template Filter (Steps 4, 6)**
Created custom Django template filter for dictionary access:

**New File: `data_import/templatetags/import_filters.py`**
```python
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a key.
    Usage: {{ mydict|get_item:key }}
    """
    if dictionary is None:
        return None
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None
```

**Templates Updated:**
```django
{% load import_filters %}

{{ models_fields|get_item:model_name }}  ✅ Now works
{{ existing_formats_dict|get_item:csv_column }}  ✅ Now works
```

---

### **Solution 3: Add Value to Object (Step 9)**
For nested dictionary with tuple keys, added value directly to the object:

**View (`step9_missing_relations.py`):**
```python
# Get existing value if any
existing_value = existing_relations_dict.get((model_name, fk_field_name), '')

missing_relations.append({
    'model_name': model_name,
    'field_name': fk_field_name,
    'existing_value': existing_value,  # ✅ Add to object
    ...
})
```

**Template (`step9_missing_relations.html`):**
```django
<input type="text" value="{{ relation.existing_value }}">  ✅ Direct access
```

---

## Files Created

1. **`/data_import/templatetags/__init__.py`** - Package init (empty)
2. **`/data_import/templatetags/import_filters.py`** - Custom filters

---

## Files Modified

### **Views:**
1. `/data_import/views/step2_patient_id.py` - Added count calculations
2. `/data_import/views/step9_missing_relations.py` - Added existing_value to objects

### **Templates:**
1. `/templates/data_import/step2_patient_id.html` - Use count variables
2. `/templates/data_import/step4_field_mapping.html` - Load custom filters
3. `/templates/data_import/step6_date_format.html` - Load custom filters
4. `/templates/data_import/step9_missing_relations.html` - Load custom filters, use existing_value

---

## Custom Filter Usage

To use the custom `get_item` filter in any template:

```django
{% load import_filters %}

{# Simple dictionary access #}
{{ my_dict|get_item:"key_name" }}
{{ my_dict|get_item:variable_key }}

{# Chained access #}
{{ outer_dict|get_item:key1|get_item:key2 }}
```

---

## Best Practices Applied

### ✅ **Do:**
- Calculate complex logic in views (Python)
- Pass simple values to templates
- Create custom filters for reusable operations
- Keep templates simple and readable

### ❌ **Don't:**
- Use Jinja2-specific filters in Django templates
- Perform complex calculations in templates
- Chain too many filters together
- Assume filters from other template engines exist

---

## Django vs Jinja2 Filters

| Jinja2 Filter | Django Equivalent | Solution |
|---------------|-------------------|----------|
| `selectattr` | None | Calculate in view |
| `rejectattr` | None | Calculate in view |
| `get_item` | None | Custom filter |
| `items()` | `items` | Built-in ✅ |
| `length` | `length` | Built-in ✅ |

---

## Testing Checklist

- [x] Step 2 displays patient counts correctly
- [x] Step 4 field mapping works with nested dictionaries
- [x] Step 6 date format selection works
- [x] Step 9 missing relations shows existing values
- [x] No TemplateSyntaxError on any step
- [x] Custom filters load correctly

---

## Status

✅ **ALL TEMPLATE FILTER ISSUES FIXED**

All templates now use proper Django template syntax and custom filters where needed. No Jinja2-specific filters remain.

**Date:** November 6, 2025  
**Files Modified:** 6  
**Files Created:** 2
