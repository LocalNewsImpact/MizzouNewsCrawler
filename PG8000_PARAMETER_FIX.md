# pg8000 Parameter Binding Fix

## Problem Summary

The Argo workflow test failed with:
```
pg8000.exceptions.InterfaceError: Only %s and %% are supported in the query.
```

## Root Cause

When using `pandas.read_sql_query(query_string, engine, params=dict)`:
- pandas passes the raw SQL string and params dict directly to the database driver
- pg8000 (used by Cloud SQL Python Connector) only supports **positional** parameters (`%s`)
- pg8000 does NOT support named parameters like `%(param_name)s`

## Solution

Wrap SQL queries with SQLAlchemy's `text()` function:

```python
from sqlalchemy import text as sql_text

# WRONG - Direct string with named params fails with pg8000
query = "SELECT * FROM table WHERE id = %(id)s"
df = pd.read_sql_query(query, engine, params={'id': 123})  # ❌ FAILS

# CORRECT - Use text() wrapper with :param syntax
query = sql_text("SELECT * FROM table WHERE id = :id")
df = pd.read_sql_query(query, engine, params={'id': 123})  # ✅ WORKS
```

SQLAlchemy's `text()` automatically converts `:param` syntax to whatever the underlying driver needs:
- For pg8000: converts to `%s` positional parameters
- For psycopg2: keeps named parameters
- Works transparently across drivers

## Files Fixed

1. **src/crawler/discovery.py**
   - Added `text()` wrapper to `pd.read_sql_query()` call
   - Changed parameter syntax from `%(param)s` back to `:param`

2. **src/cli/commands/extraction.py**
   - Already used `text()` for SQL statements
   - Changed parameter syntax from `%(param)s` back to `:param`

3. **src/services/url_verification.py**
   - Already used `text()` for UPDATE statements
   - Changed parameter syntax from `%(param)s` back to `:param`

4. **src/models/versioning.py**
   - Already used `text()` for PostgreSQL advisory lock functions
   - Changed parameter syntax from `%(param)s` back to `:param`

## Testing

The fix was committed as `3155e6a` and will be tested in the next Argo workflow run after rebuilding the processor image.

## Commits

- `5dd4dda`: Initial attempt with `%(param)s` syntax (WRONG approach)
- `3155e6a`: Corrected fix using `text()` with `:param` syntax (CORRECT)
