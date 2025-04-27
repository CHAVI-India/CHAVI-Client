"""
API endpoint mappings for lookup models.

This file defines how each model maps to the external API endpoints.
You can customize the endpoint and primary key field for each model.
"""

# Format: 'model_name': {'endpoint': 'api_endpoint', 'pk_field': 'primary_key_field'}
API_MAPPINGS = {
    # Examples:
    'lookuplaterality': {'endpoint': 'laterality', 'pk_field': 'code'},
    'lookupicdcode': {'endpoint': 'icd-codes', 'pk_field': 'code'},
    'lookupfmacode': {'endpoint': 'fma-codes', 'pk_field': 'code'},
    'lookuppresentation': {'endpoint': 'presentations', 'pk_field': 'code'},
    'lookupoutcometype': {'endpoint': 'outcome-types', 'pk_field': 'code'},
    'lookuplesiontype': {'endpoint': 'lesion-types', 'pk_field': 'code'},
    'lookupresponsetype': {'endpoint': 'response-types', 'pk_field': 'code'},
    'lookupprotein': {'endpoint': 'proteins', 'pk_field': 'code'},
    'lookupgene': {'endpoint': 'genes', 'pk_field': 'code'},
    'lookuptreatmentintent': {'endpoint': 'treatment-intents', 'pk_field': 'code'},
    'lookuptreatmentsequence': {'endpoint': 'treatment-sequences', 'pk_field': 'code'},
    'lookupsystemicagent': {'endpoint': 'systemic-agents', 'pk_field': 'code'},
    'lookupvolumeunits': {'endpoint': 'volume-units', 'pk_field': 'code'},
    'lookupsizeunits': {'endpoint': 'size-units', 'pk_field': 'code'},
    'lookupdoseunits': {'endpoint': 'dose-units', 'pk_field': 'code'},
    'lookuplabresultsunits': {'endpoint': 'lab-results-units', 'pk_field': 'code'},
    'lookupmassunits': {'endpoint': 'mass-units', 'pk_field': 'code'},
    'lookupdrugroute': {'endpoint': 'drug-routes', 'pk_field': 'code'},
    'lookupctcaegrade': {'endpoint': 'ctcae-grades', 'pk_field': 'code'},
    'lookupoutcome': {'endpoint': 'outcomes', 'pk_field': 'code'},
    'lookupstagingsystem': {'endpoint': 'staging-systems', 'pk_field': 'code'},
    'lookupajccstageprefix': {'endpoint': 'ajcc-stage-prefixes', 'pk_field': 'code'},
    'lookupajccstagesuffix': {'endpoint': 'ajcc-stage-suffixes', 'pk_field': 'code'},
    'lookupajccstagedescriptor': {'endpoint': 'ajcc-t-stage-descriptors', 'pk_field': 'code'},
    'lookupajccnstagedescriptor': {'endpoint': 'ajcc-n-stage-descriptors', 'pk_field': 'code'},
    'lookupajccmstagedescriptor': {'endpoint': 'ajcc-m-stage-descriptors', 'pk_field': 'code'},
    'lookupstagedescriptor': {'endpoint': 'stage-descriptors', 'pk_field': 'code'},
    'lookupdiagnosticmodality': {'endpoint': 'diagnostic-modalities', 'pk_field': 'code'},
    'lookupsystemictherapytype': {'endpoint': 'systemic-therapy-types', 'pk_field': 'code'},
    'lookupradiotherapyvolumetypes': {'endpoint': 'radiotherapy-volume-types', 'pk_field': 'code'},
    'lookuppathology': {'endpoint': 'pathologies', 'pk_field': 'code'},
    'lookupgrade': {'endpoint': 'grades', 'pk_field': 'code'},
    'lookuppathologydescriptors': {'endpoint': 'pathology-descriptors', 'pk_field': 'code'},
    'lookupmajorcancercategory': {'endpoint': 'major-cancer-categories', 'pk_field': 'code'},
    'lookupradiotherapymodality': {'endpoint': 'radiotherapy-modalities', 'pk_field': 'code'},
    'lookupradiotherapytype': {'endpoint': 'radiotherapy-types', 'pk_field': 'code'},
    'lookupradiotherapytechnique': {'endpoint': 'radiotherapy-techniques', 'pk_field': 'code'},
    'lookupclinicalsignificance': {'endpoint': 'clinical-significances', 'pk_field': 'code'},
    'lookupihcresult': {'endpoint': 'ihc-results', 'pk_field': 'code'},
    'lookupihcstainingintensity': {'endpoint': 'ihc-staining-intensities', 'pk_field': 'code'},
    'lookupmarginstatus': {'endpoint': 'margin-statuses', 'pk_field': 'code'},
    'lookuptreatmenteffect': {'endpoint': 'treatment-effects', 'pk_field': 'code'},
    'lookupstagingtype': {'endpoint': 'staging-systems', 'pk_field': 'code'},
    'lookupsystemictherapyregimen': {'endpoint': 'systemic-therapy-regimens', 'pk_field': 'code'},
    'lookuprtlocation': {'endpoint': 'rt-locations', 'pk_field': 'code'},
    'lookuplaboratorytest': {'endpoint': 'laboratory-tests', 'pk_field': 'code'},
    'lookupsymptoms': {'endpoint': 'symptoms', 'pk_field': 'code'},
    'lookupseverity': {'endpoint': 'severities', 'pk_field': 'code'},
    'lookupihcantibody': {'endpoint': 'ihc-antibodies', 'pk_field': 'code'},
    'lookupcomorbidity': {'endpoint': 'comorbidities', 'pk_field': 'code'},
    'lookupperformancestatus': {'endpoint': 'performance-statuses', 'pk_field': 'code'},
    'lookupexpressionunits': {'endpoint': 'expression-units', 'pk_field': 'code'},
    'lookupcytogeneticabnormality': {'endpoint': 'cytogenetic-abnormalities', 'pk_field': 'code'},
    'lookupepigeneticabnormalitytype': {'endpoint': 'epigenetic-abnormality-types', 'pk_field': 'code'},
    'lookupsurgicalprocedure': {'endpoint': 'surgical-procedures', 'pk_field': 'code'},
    'lookupnodalassessmenttype': {'endpoint': 'nodal-assessment-types', 'pk_field': 'code'},

    

    
    
    
    
    
    
    # Add specific mappings for models where the endpoint doesn't match the model name
    # or where the primary key field isn't 'code'
    
    # For all other models, defaults will be used:
    # - endpoint: model_name (lowercase)
    # - pk_field: 'code'
}

def get_api_mapping(model_name: str) -> dict:
    """
    Get API mapping for a model.
    
    Args:
        model_name: Model name (lowercase)
        
    Returns:
        Dict with 'endpoint' and 'pk_field'
    """
    mapping = API_MAPPINGS.get(model_name, {})
    return {
        'endpoint': mapping.get('endpoint', model_name),
        'pk_field': mapping.get('pk_field', 'code')
    } 