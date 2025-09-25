# Critical Information Needs Coverage
Generated on September 25, 2025.
This report summarizes publications, story counts, and Critical Information Needs (CIN) distribution for Boone, Audrain, and Osage counties based on `reports/cin_labels_with_sources.csv`.

## Boone County
| Publication | Stories | Critical Information Needs Mix |
| --- | ---: | --- |
| ABC 17 KMIZ News | 1 | Emergencies and Public Safety 1 (100.0%) |
| Boone County Journal | 16 | Civic Life 6 (37.5%)<br>Civic information 4 (25.0%)<br>Education 2 (12.5%)<br>Political life 2 (12.5%)<br>Emergencies and Public Safety 1 (6.2%)<br>Sports 1 (6.2%) |
| Centralia Fireside Guard | 11 | Sports 5 (45.5%)<br>Civic information 3 (27.3%)<br>Civic Life 2 (18.2%)<br>Emergencies and Public Safety 1 (9.1%) |
| Columbia Daily Tribune | 24 | Sports 10 (41.7%)<br>Civic Life 9 (37.5%)<br>Civic information 3 (12.5%)<br>Education 1 (4.2%)<br>Emergencies and Public Safety 1 (4.2%) |
| Columbia Missourian | 13 | Sports 6 (46.2%)<br>Education 3 (23.1%)<br>Civic information 2 (15.4%)<br>Civic Life 1 (7.7%)<br>Political life 1 (7.7%) |
| KBIA | 25 | Civic information 7 (28.0%)<br>Political life 5 (20.0%)<br>Civic Life 4 (16.0%)<br>Health 3 (12.0%)<br>Emergencies and Public Safety 2 (8.0%)<br>Environment and Planning 2 (8.0%)<br>Education 1 (4.0%)<br>Transportation Systems 1 (4.0%) |

## Audrain County
| Publication | Stories | Critical Information Needs Mix |
| --- | ---: | --- |
| The Mexico Ledger | 24 | Civic Life 8 (33.3%)<br>Sports 8 (33.3%)<br>Civic information 4 (16.7%)<br>Emergencies and Public Safety 4 (16.7%) |
| Vandalia Leader | 10 | Civic Life 3 (30.0%)<br>Sports 3 (30.0%)<br>Civic information 2 (20.0%)<br>Environment and Planning 1 (10.0%)<br>Political life 1 (10.0%) |

## Osage County
| Publication | Stories | Critical Information Needs Mix |
| --- | ---: | --- |
| The Unterrified Democrat | 21 | Sports 7 (33.3%)<br>Civic information 6 (28.6%)<br>Civic Life 3 (14.3%)<br>Emergencies and Public Safety 2 (9.5%)<br>Education 1 (4.8%)<br>Environment and Planning 1 (4.8%)<br>Political life 1 (4.8%) |

---

### Regenerate summaries

Activate the virtual environment from the project root and run:

```bash
source venv/bin/activate
python scripts/report_cin_county_summary.py --format both
```

Use `--format csv` or `--format markdown` to emit a single file. Outputs are written to `reports/cin_county_summary.csv` and `reports/cin_county_summary.md`.
