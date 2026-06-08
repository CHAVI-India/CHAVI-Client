# Semantic Search for Lookup Matching - Setup Guide

## Overview

This system uses **pgvector** and **sentence transformers** to perform semantic search on lookup tables, enabling accurate matching of extracted text to lookup codes even when the text doesn't match exactly.

## Architecture

### Components

1. **EmbeddingConfiguration** - Stores embedding model settings
2. **LookupEmbedding** - Pre-computed embeddings for lookup entries (uses pgvector)
3. **SemanticSearchService** - Performs similarity search
4. **Management Command** - Computes/refreshes embeddings
5. **InstructorExtractionService** - Integrated with semantic search

### Workflow

```
1. Pre-compute Phase (Manual):
   └─> python manage.py compute_lookup_embeddings
       ├─> Load embedding model
       ├─> For each lookup table:
       │   ├─> Get all records
       │   ├─> Compute embeddings
       │   └─> Store in LookupEmbedding table
       └─> Done!

2. Extraction Phase (Automatic):
   └─> Document arrives
       ├─> Compute document embedding
       ├─> Find top-K similar lookup entries (pgvector)
       ├─> Show only relevant options to LLM
       ├─> LLM matches to best option
       └─> Store both label and code
```

## Installation

### 1. Install Dependencies

```bash
# Install pgvector extension for PostgreSQL
# On Ubuntu/Debian:
sudo apt-get install postgresql-contrib postgresql-server-dev-all
cd /tmp
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

# Restart PostgreSQL
sudo systemctl restart postgresql

# Install Python packages
pip install pgvector sentence-transformers
```

### 2. Enable pgvector in Database

```sql
-- Connect to your database
psql -U postgres -d chaviclient

-- Enable extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify
\dx vector
```

### 3. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

## Configuration

### 1. Create Embedding Configuration

Go to Django Admin → Embedding Configurations → Add New

**Recommended Settings:**

```
Model Name: all-MiniLM-L6-v2
Model Provider: sentence-transformers
Embedding Dimension: 384
Is Active: ✓
Similarity Threshold: 0.7
Top K Results: 5
```

**Alternative Models:**

- **Fast & General**: `all-MiniLM-L6-v2` (384 dims)
- **Medical-Specific**: `pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb` (768 dims)
- **Best Quality**: `all-mpnet-base-v2` (768 dims)
- **OpenAI**: `text-embedding-3-small` (1536 dims, requires API key)

### 2. Compute Embeddings

```bash
# Compute embeddings for all lookup tables
python manage.py compute_lookup_embeddings

# Refresh all embeddings (delete and recompute)
python manage.py compute_lookup_embeddings --refresh

# Process specific table only
python manage.py compute_lookup_embeddings --table lookupicdcode

# Custom batch size
python manage.py compute_lookup_embeddings --batch-size 50
```

**Expected Output:**
```
Using embedding model: all-MiniLM-L6-v2
Loading model: all-MiniLM-L6-v2...
Model loaded successfully

Processing table: lookupicdcode
  Processing field: icd_description
    Total records: 325
    Processed: 100/325
    Processed: 200/325
    Processed: 325/325
  Completed lookupicdcode: 325 embeddings created

Completed! Processed 325 embeddings.
```

## Usage

### Automatic Integration

Semantic search is **automatically used** during extraction:

1. Document arrives for extraction
2. System computes embedding for document context
3. For each lookup field, finds top 5 most similar options
4. Shows only these relevant options to LLM
5. LLM matches extracted text to best option
6. System stores both label and code

### Example

**Document:**
```
DIAGNOSIS: ENDOCERVICAL ADENOCARCINOMA, HPV-ASSOCIATED
```

**Without Semantic Search:**
- LLM sees all 325 ICD codes
- May get confused or pick wrong code
- Token limit issues

**With Semantic Search:**
```
Valid Options (most relevant):
- Endocervical adenocarcinoma
- Cervical adenocarcinoma
- Adenocarcinoma of cervix uteri
- Malignant neoplasm of cervix
- Cervical carcinoma

LLM matches: "Endocervical adenocarcinoma"
System maps to code: "2C77.0"
Stores: {'label': 'Endocervical adenocarcinoma', 'code': '2C77.0'}
```

## Monitoring

### Check Embedding Status

```python
from extractor.models import LookupEmbedding, EmbeddingConfiguration

# Get active config
config = EmbeddingConfiguration.objects.filter(is_active=True).first()
print(f"Active model: {config.model_name}")

# Count embeddings
total = LookupEmbedding.objects.count()
print(f"Total embeddings: {total}")

# By table
from django.db.models import Count
by_table = LookupEmbedding.objects.values('content_type__model').annotate(count=Count('id'))
for item in by_table:
    print(f"{item['content_type__model']}: {item['count']}")
```

### Test Semantic Search

```python
from extractor.services.semantic_search import SemanticSearchService
from lookup.models import LookupICDCode

# Test query
results = SemanticSearchService.find_similar_lookup_entries(
    LookupICDCode,
    'icd_code',
    'icd_description',
    'ENDOCERVICAL ADENOCARCINOMA',
    top_k=5
)

for r in results:
    print(f"{r['code']}: {r['label']} (similarity: {r['similarity']:.3f})")
```

## Maintenance

### When to Refresh Embeddings

- **After importing new lookup data**
- **When changing embedding model**
- **If similarity results seem poor**

```bash
python manage.py compute_lookup_embeddings --refresh
```

### Performance Optimization

**For large lookup tables (>10,000 entries):**

1. **Add pgvector index:**
```sql
CREATE INDEX ON extractor_lookupembedding 
USING ivfflat (embedding vector_cosine_ops) 
WITH (lists = 100);
```

2. **Increase batch size:**
```bash
python manage.py compute_lookup_embeddings --batch-size 500
```

3. **Use GPU for embedding computation:**
```python
# In semantic_search.py
model = SentenceTransformer('all-MiniLM-L6-v2', device='cuda')
```

## Troubleshooting

### Issue: "No active embedding configuration found"
**Solution:** Create an EmbeddingConfiguration in Django admin and set `is_active=True`

### Issue: "No module named 'sentence_transformers'"
**Solution:** `pip install sentence-transformers`

### Issue: "pgvector extension not found"
**Solution:** Install pgvector extension (see Installation section)

### Issue: Embeddings taking too long
**Solution:** 
- Use smaller model (all-MiniLM-L6-v2)
- Increase batch size
- Use GPU if available

### Issue: Poor matching results
**Solution:**
- Try medical-specific model (BioBERT)
- Adjust similarity_threshold (lower = more results)
- Increase top_k_results

## Advanced Configuration

### Using OpenAI Embeddings

```python
# In Django Admin
Model Name: text-embedding-3-small
Model Provider: openai
Embedding Dimension: 1536
API Key: sk-...
```

### Custom Embedding Model

```python
# In semantic_search.py, add new provider:
elif config.model_provider == 'custom':
    from your_module import YourEmbeddingModel
    cls._embedding_model = YourEmbeddingModel()
```

## Benefits

✅ **Accurate Matching** - Finds similar terms even with different wording
✅ **Handles Abbreviations** - "CA" matches "Carcinoma"  
✅ **Case Insensitive** - Works regardless of capitalization  
✅ **Scalable** - Pre-computed embeddings = fast search  
✅ **Reduced Token Usage** - Show only relevant options to LLM  
✅ **Better Extraction** - LLM gets focused, relevant choices  

## Next Steps

1. ✅ Install dependencies
2. ✅ Enable pgvector
3. ✅ Run migrations
4. ✅ Create embedding configuration
5. ✅ Compute embeddings
6. ✅ Test extraction with semantic search
7. 🔄 Monitor and optimize
