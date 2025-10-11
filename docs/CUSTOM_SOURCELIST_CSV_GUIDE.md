# Custom Source List - CSV Setup Guide

## Why Use CSV?

The CSV setup method is **recommended** because it allows you to specify complete source metadata including:
- ✅ City and County (required for gazetteer and geographic filtering)
- ✅ Physical address and ZIP code
- ✅ Source type (newspaper, TV, radio, etc.)
- ✅ Owner organization
- ✅ Description

This metadata enables:
- **Geographic entity matching** (gazetteer finds local places, schools, businesses)
- **Better ML classification** (knows source context)
- **Proper filtering** (can filter by county, city, etc.)

## CSV Template

Copy this template to create your source metadata file:

```csv
name,slug,source_url,source_name,city,county,state,address,zip_code,source_type,owner,description
Special Project 2025,special-project-2025,https://example.com,Example Daily News,Springfield,Greene County,Missouri,123 Main St,65806,newspaper,Example Media Group,Custom source list for special project
```

### Required Columns

- **name**: Human-readable dataset name (e.g., "Client Project 2025")
- **slug**: URL-safe identifier (e.g., "client-project-2025")
- **source_url**: Homepage URL (e.g., "https://example.com")
- **source_name**: Publisher display name (e.g., "Example Daily News")

### Optional but Recommended

- **city**: City name (e.g., "Springfield") - **Needed for gazetteer!**
- **county**: County name (e.g., "Greene County") - **Needed for geographic filtering!**
- **state**: State name (e.g., "Missouri") - **Important for geographic context!**
- **address**: Physical address (e.g., "123 Main St")
- **zip_code**: ZIP/postal code (e.g., "65806")
- **source_type**: Type (e.g., "newspaper", "TV", "radio", "online")
- **owner**: Owner organization (e.g., "Example Media Group")
- **description**: Dataset description (optional)

## Setup Steps

### 1. Create Source Metadata CSV

```bash
# Copy template
cp data/source_metadata_template.csv data/my_source.csv

# Edit with your source information
nano data/my_source.csv
```

Example `my_source.csv`:

```csv
name,slug,source_url,source_name,city,county,state,address,zip_code,source_type,owner,description
Herald Analysis 2025,herald-analysis-2025,https://townherald.com,Town Herald,Columbia,Boone County,Missouri,101 E Broadway,65201,newspaper,Herald Publishing Co,Analysis of Town Herald coverage 2020-2025
```

### 2. Create Dataset from CSV

```bash
python scripts/custom_sourcelist_workflow.py create-from-csv \
    --csv-file data/my_source.csv
```

**Output:**
```
✓ Dataset 'herald-analysis-2025' already exists (ID: 123-uuid)
✓ Created source 'townherald.com' (ID: 456-uuid)
  City: Columbia
  County: Boone County
✓ Linked dataset to source

✅ Setup complete!
   Dataset ID: 123-uuid
   Source ID: 456-uuid

📝 Next step: Import URLs with:
   python scripts/custom_sourcelist_workflow.py import-urls \
       --dataset-slug herald-analysis-2025 \
       --urls-file urls.txt
```

### 3. Create URLs File

```bash
# urls.txt
https://townherald.com/article-1
https://townherald.com/article-2
https://townherald.com/article-3
```

### 4. Import URLs

```bash
python scripts/custom_sourcelist_workflow.py import-urls \
    --dataset-slug herald-analysis-2025 \
    --urls-file urls.txt
```

### 5. (Optional) Create Gazetteer

With city and county metadata, you can now create a gazetteer:

```bash
python scripts/populate_gazetteer.py \
    --dataset-slug herald-analysis-2025 \
    --source-id 456-uuid
```

This will:
- Query OSM for places in Columbia, Boone County
- Add schools, businesses, landmarks, government buildings
- Enable entity extraction to find local references in articles

### 6. Run Extraction Pipeline

```bash
python scripts/custom_sourcelist_workflow.py extract \
    --dataset-slug herald-analysis-2025 \
    --max-articles 100
```

### 7. Export Results

```bash
python scripts/custom_sourcelist_workflow.py export \
    --dataset-slug herald-analysis-2025 \
    --output herald_results.xlsx
```

## Alternative: Command-Line Method

If you prefer command-line arguments instead of CSV:

```bash
python scripts/custom_sourcelist_workflow.py create-dataset \
    --name "Herald Analysis 2025" \
    --slug "herald-analysis-2025" \
    --source-url "https://townherald.com" \
    --source-name "Town Herald" \
    --city "Columbia" \
    --county "Boone County" \
    --address "101 E Broadway" \
    --zip-code "65201" \
    --source-type "newspaper" \
    --owner "Herald Publishing Co"
```

**Tip:** CSV method is easier for tracking and reproducibility!

## Why City and County Matter

### Without Location Metadata

```python
# Can only do basic extraction
article.content  # "Mayor Smith announced new school funding..."

# No gazetteer matching - can't identify:
# - Which school district?
# - Which city's mayor?
# - Local business names
```

### With Location Metadata

```python
# Gazetteer enables smart matching
article.content  # "Mayor Smith announced new school funding..."

# Can now match:
# ✓ "Smith" → "Mayor John Smith, Columbia"
# ✓ "school" → "Columbia Public Schools" (from gazetteer)
# ✓ "downtown" → specific downtown area coordinates
```

## Common Scenarios

### Single Source, Multiple Projects

If you're analyzing the same source for different time periods:

```csv
# project_2020.csv
name,slug,source_url,source_name,city,county,...
Herald 2020,herald-2020,https://townherald.com,Town Herald,Columbia,Boone County,...

# project_2021.csv  
name,slug,source_url,source_name,city,county,...
Herald 2021,herald-2021,https://townherald.com,Town Herald,Columbia,Boone County,...
```

Each gets its own dataset but shares the same source metadata.

### Multiple Sources, One Project

Create multiple CSVs and combine:

```bash
# Create first source
python scripts/custom_sourcelist_workflow.py create-from-csv \
    --csv-file source1.csv

# Create second source with same dataset slug
python scripts/custom_sourcelist_workflow.py create-from-csv \
    --csv-file source2.csv

# Note: Manually ensure slug is the same in both CSVs if you want
# them in one dataset, or use different slugs for separation
```

## Troubleshooting

### "City Required for Gazetteer"

If you see this warning, it means gazetteer creation will fail. Always include city and county:

```csv
# ❌ Won't work for gazetteer
...,,,,...  # Empty city/county

# ✅ Works
...,Springfield,Greene County,...
```

### "Source Already Exists"

If the source hostname already exists (e.g., from Missouri records), the script will:
1. Use the existing source
2. Create a new DatasetSource link
3. Your articles will still be isolated by dataset_id

### CSV Encoding Issues

If you have special characters:

```bash
# Save CSV as UTF-8
file -I my_source.csv  # Should show "charset=utf-8"

# Or specify encoding in Python
# (Currently auto-detected by pandas)
```

## Best Practices

1. **Always include city and county** - Enables gazetteer and geographic filtering
2. **Use consistent naming** - Same slug format across projects
3. **Keep CSV in version control** - Track metadata changes
4. **Document source_type** - Helps with analysis (newspaper vs TV vs radio)
5. **Include full address** - Useful for geolocation and context

## Template Location

The template CSV is located at:
```
data/source_metadata_template.csv
```

Copy and modify it for your needs:
```bash
cp data/source_metadata_template.csv data/my_project.csv
nano data/my_project.csv  # Edit your information
python scripts/custom_sourcelist_workflow.py create-from-csv --csv-file data/my_project.csv
```

## What Gets Created

When you run `create-from-csv`, the system creates:

1. **Dataset Record**
   - ID: Generated UUID
   - Slug: From CSV
   - Label: From CSV "name"
   - is_public: False (private)

2. **Source Record**
   - ID: Generated UUID
   - host: Parsed from source_url
   - host_norm: Lowercased host
   - canonical_name: From CSV "source_name"
   - city, county: From CSV
   - type, owner: From CSV
   - meta: JSON with address, zip_code, etc.

3. **DatasetSource Link**
   - Links dataset ↔ source
   - Enables queries like "all articles from this source in this dataset"

## Next Steps After Setup

Once you've created your dataset with CSV:

1. ✅ Import URLs (see step 4 above)
2. ✅ (Optional) Create gazetteer if you provided city/county
3. ✅ Run extraction pipeline
4. ✅ Export results to Excel
5. ✅ Analyze your data!

Your articles will be completely isolated from Missouri records because they have a unique dataset_id.
