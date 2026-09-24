-- Newsrooms March did not collect, for the visuals builder's LOCATOR MAP.
-- Run against the crawler database; the result is the CSV beside this file.
-- Nothing here writes.
--
-- TWO REASONS, ONE MAP, in the `reason` column:
--
--   replica or print only   The paper publishes no web edition we can read --
--                           a flipbook replica, or print alone. There is
--                           nothing to collect, in March or ever. These are
--                           NOT in `sources`: they were found in the Missouri
--                           Blue Book listing and ruled out by review, so they
--                           are carried here as literals with the reason that
--                           review recorded (see
--                           mo_bluebook_missing_from_ours.csv, website_status).
--
--   not attempted in March  An ACTIVE source in the dataset with no
--                           `candidate_links` discovered in March 2026. The
--                           site is collectable; March simply never reached it.
--
-- EXCLUDED: the ten sources added 2026-09-24 from the Blue Book. They have no
-- March links either, but they did not exist in March, so calling them "not
-- attempted" would read as a gap in the crawl rather than a gap in the list.
-- They are on mo_new_newsrooms_locator.csv instead.
--
-- WHY THIS SHAPE. A locator takes one column of area codes and no value. The
-- column MUST be named `geoid`: `visuals.types.GEO_NAMES` is the set of header
-- names that let a 5-digit code read as geography, and a Missouri code has no
-- leading zero, so under any other name it types as a number, the role refuses
-- it and the map draws blank. `city` is second because `renderLocator` takes
-- the first string column after the key as the label and tooltip.
--
-- A LOCATOR CANNOT COLOUR BY `reason` -- it highlights, it does not shade. To
-- show the two apart, build two visuals filtered on `reason`, or use a shaded
-- map keyed on a number.

WITH replica_or_print(geoid, city, county, newspaper, host) AS (VALUES
    ('29087', 'Mound City',   'Holt',        'Mound City News',               'www.moundcitynews.com'),
    ('29095', 'Oak Grove',    'Jackson',     'Focus On Oak Grove',            'www.theodessan.net'),
    ('29107', 'Odessa',       'Lafayette',   'Odessa Odessan',                'www.theodessan.net'),
    ('29133', 'Charleston',   'Mississippi', 'Charleston Enterprise-Courier', 'www.enterprisecourier.com'),
    ('29133', 'East Prairie', 'Mississippi', 'East Prairie Eagle',            'www.enterprisecourier.com'),
    ('29141', 'Versailles',   'Morgan',      'Morgan County Statesman',       'www.morgancountystatesman.com'),
    ('29195', 'Slater',       'Saline',      'Slater Main Street News',       'www.slatermainstreetnews.com'),
    ('29215', 'Summersville', 'Texas',       'Summersville Beacon',           'www.sbeacon.com')
),

-- Added 2026-09-24; no March links because they were not in the list then.
added_since_march(host) AS (VALUES
    ('www.stclaircourier.com'), ('www.charitonmarquee.com'),
    ('www.clintoncountyleader.com'), ('www.hermitageindex.com'),
    ('www.htjournal.net'), ('www.monroe-ralls.com'), ('www.sbj.net'),
    ('www.tiptontimes.com'), ('www.tribuneandtimes.com'),
    ('www.westnewsmagazine.com')
),

-- County name -> GEOID for the counties in play. The crawler stores a name and
-- the builder joins on a code. The full 115 are in
-- src/enrichment/reference/census_counties.csv, USPS = 'MO'.
geoid(county, geoid) AS (VALUES
    ('Barry','29009'), ('Cass','29037'), ('Crawford','29055'), ('Greene','29077'),
    ('Iron','29093'), ('Jackson','29095'), ('Jefferson','29099'), ('Johnson','29101'),
    ('Lafayette','29107'), ('Madison','29123'), ('Reynolds','29179'),
    ('Schuyler','29197'), ('Shannon','29203'), ('St. Charles','29183'),
    ('Stone','29209'), ('Wright','29229')
),

not_attempted AS (
    SELECT s.host, s.canonical_name, s.city, s.county
      FROM sources s
      JOIN dataset_sources ds ON ds.source_id = s.id
      JOIN datasets d ON d.id = ds.dataset_id AND d.slug = 'Mizzou-Missouri-State'
      LEFT JOIN candidate_links cl ON cl.source_id = s.id
     WHERE s.status = 'active'
       AND s.host NOT IN (SELECT host FROM added_since_march)
     GROUP BY s.host, s.canonical_name, s.city, s.county
    HAVING count(cl.id) FILTER (
             WHERE cl.discovered_at >= DATE '2026-03-01'
               AND cl.discovered_at <  DATE '2026-04-01') = 0
)

SELECT geoid, city, county, 'replica or print only' AS reason, newspaper, host
  FROM replica_or_print
UNION ALL
SELECT g.geoid, n.city, n.county, 'not attempted in March', n.canonical_name, n.host
  FROM not_attempted n JOIN geoid g ON g.county = n.county
 ORDER BY 4, 3, 2;
