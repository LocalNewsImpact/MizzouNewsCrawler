#!/usr/bin/env bash
# Bring production's alembic_version in line with the schema that is actually
# there, then apply pending migrations.
#
# Production sits at cea12b602254 while the repo head is further ahead, and two
# of the intervening migrations were applied to the database but never recorded.
# `alembic upgrade head` therefore fails immediately, trying to re-add columns
# that already exist. Verified against production on 2026-07-20:
#
#   cea12b602254 -> f7a2b9c1d3e4  auth columns on sources   ALREADY APPLIED
#   f7a2b9c1d3e4 -> b2d9f4c7e1a3  datasets.created_at       GENUINELY MISSING
#   b2d9f4c7e1a3 -> c4e8a1f52b7d  uq_articles_url           ALREADY APPLIED
#   c4e8a1f52b7d -> d5f1a2b3c4e6  entities_extracted_at     NOT APPLIED
#
# So: stamp what is already true, run what is genuinely missing.
#
# datasets.created_at is worth understanding before running: the table was
# created without the column while the Dataset model has always declared it, so
# ORM inserts fail with `column "created_at" of relation "datasets" does not
# exist` and poison the surrounding transaction. That migration repairs the
# breakage — it does not introduce it.
#
# MUST run from the migrator image (the processor image ships no alembic/), and
# that image must be built from a commit containing d5f1a2b3c4e6.
#
# Re-verify before trusting the plan — drift can change:
#   SELECT version_num FROM alembic_version;
#   SELECT 1 FROM information_schema.columns
#    WHERE table_name='datasets' AND column_name='created_at';

set -euo pipefail

echo "== current alembic state =="
python -m alembic current

echo
echo "== 1/4 stamp f7a2b9c1d3e4 (sources auth columns already present) =="
python -m alembic stamp f7a2b9c1d3e4

echo
echo "== 2/4 upgrade b2d9f4c7e1a3 (adds the missing datasets.created_at) =="
python -m alembic upgrade b2d9f4c7e1a3

echo
echo "== 3/4 stamp c4e8a1f52b7d (uq_articles_url already present) =="
python -m alembic stamp c4e8a1f52b7d

echo
echo "== 4/4 upgrade head (entities_extracted_at + partial index) =="
# That migration lifts statement_timeout itself: the role caps statements at
# 120s and the backfill touches ~122k rows.
python -m alembic upgrade head

echo
echo "== final state =="
python -m alembic current
