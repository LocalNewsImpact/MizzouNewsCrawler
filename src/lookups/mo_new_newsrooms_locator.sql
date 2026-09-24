-- The counties and cities of the newly added Mizzou newsrooms, for the visuals
-- builder's LOCATOR MAP. Run against the crawler database; the result is the
-- CSV beside this file. Nothing here writes.
--
-- WHY THIS SHAPE. A locator map takes one column of area codes and no value:
-- an area is in the list or it is not (visuals/types.py, ChartType "locator").
--
--   `geoid`   MUST be that name. `visuals.types.GEO_NAMES` is the set of header
--             names that let a 5-digit code read as geography; a Missouri code
--             has no leading zero, so 29041 survives float() and under any
--             other header types as NUMBER, which the role refuses and the map
--             draws blank with nothing on the page to say why.
--   `city`    is second on purpose. The renderer takes the first string column
--             that is not the key as the name it draws and shows on hover
--             (static/js/datadesk-chart.js, renderLocator), so the highlighted
--             counties are labelled with the town the newsroom is in.
--
-- In the builder: Locator map -> Areas to highlight = geoid -> Frame on = the
-- states the areas are in -> Name the highlighted areas = on.

WITH added(host) AS (VALUES
    ('www.stclaircourier.com'),
    ('www.charitonmarquee.com'),
    ('www.clintoncountyleader.com'),
    ('www.hermitageindex.com'),
    ('www.htjournal.net'),
    ('www.monroe-ralls.com'),
    ('www.sbj.net'),
    ('www.tiptontimes.com'),
    ('www.tribuneandtimes.com'),
    ('www.westnewsmagazine.com'),
    ('democratnewsonline.com'),
    ('www.mycnews.com'),
    ('www.trentontelegraph.com')
),

-- County name -> GEOID. The crawler stores a county NAME and the builder joins
-- on a code. Only the counties in play are listed; the full 115 are in
-- src/enrichment/reference/census_counties.csv, USPS = 'MO'.
geoid(county, geoid) AS (VALUES
    ('Cass','29037'), ('Chariton','29041'), ('Clark','29045'), ('Clinton','29049'),
    ('Greene','29077'), ('Grundy','29079'), ('Hickory','29085'), ('Madison','29123'),
    ('Moniteau','29135'), ('Monroe','29137'), ('St. Charles','29183'),
    ('St. Clair','29185'), ('St. Louis','29189')
)

SELECT g.geoid          AS geoid,
       s.city           AS city,
       s.county         AS county,
       s.canonical_name AS newspaper
  FROM sources s
  JOIN dataset_sources ds ON ds.source_id = s.id
  JOIN datasets d ON d.id = ds.dataset_id AND d.slug = 'Mizzou-Missouri-State'
  JOIN added a ON a.host = s.host
  JOIN geoid g ON g.county = s.county
 ORDER BY s.county, s.city;
