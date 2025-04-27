# Lookup App API Integration

This app provides functionality to sync lookup tables with an external API.

## Configuration

API settings are configured in your Django settings:

```python
# External API settings for lookup data
LOOKUP_API_URL = os.environ.get('LOOKUP_API_URL', '')
LOOKUP_API_KEY = os.environ.get('LOOKUP_API_KEY', '')
LOOKUP_API_TIMEOUT = int(os.environ.get('LOOKUP_API_TIMEOUT', '30'))

# Proxy settings
HTTP_PROXY = os.environ.get('HTTP_PROXY', '')
HTTPS_PROXY = os.environ.get('HTTPS_PROXY', '')
NO_PROXY = os.environ.get('NO_PROXY', '')
```

Make sure to set these environment variables in your deployment environment.

## Using the API Sync

The lookup tables in the Django admin interface have a "Sync with external API" action.
To use this:

1. Go to any lookup table in the admin interface
2. Select one or more records (or none to update all)
3. Choose "Sync selected models with external API" from the dropdown
4. Click "Go"

The system will fetch data from the configured API and update or create records as needed.

## Customizing API Endpoints

If your API endpoints don't match the model names, you can customize the mappings in 
`lookup/api_mappings.py`. For example:

```python
API_MAPPINGS = {
    'lookuplaterality': {'endpoint': 'laterality', 'pk_field': 'code'},
    'lookupoutcometype': {'endpoint': 'outcome-types', 'pk_field': 'code'},
    # Add more mappings as needed
}
```

### API URL Format

The system automatically ensures all API requests end with a trailing slash. 
You don't need to include trailing slashes in your endpoint mappings.

For example, with `LOOKUP_API_URL = 'https://api.example.com'` and an endpoint 
of `'laterality'`, the final URL will be `https://api.example.com/laterality/`.

## Authentication

The API requests include an `Authorization: Api-Key YOUR_API_KEY` header.
Make sure your API server accepts this authentication format.

## Error Handling

If there are issues with the API sync, error messages will appear in the Django admin interface.
More detailed logs can be found in your Django logs. 