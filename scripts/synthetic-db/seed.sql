-- Synthetic client-shaped database for manually exercising Integri Audit Tool
-- checks by hand (see scripts/setup-synthetic-db.sh). Deliberately messy:
-- every anti-pattern below mirrors a specific rubric bullet in
-- postgres-database-audit-rubric.md, so most of the 11 automated categories
-- have something concrete to find instead of an empty, clean database.
--
-- Run via scripts/setup-synthetic-db.sh, not directly — the setup script
-- also generates query traffic afterward that several checks depend on
-- (pg_stat_statements-based N+1/OFFSET/slow-query detection, TOAST access
-- counts).

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- uuid PK (mixed PK type family vs orders/products -> 01.06); tenant_id with
-- no RLS enabled anywhere -> 07.03; email is PII-shaped with no column
-- comment -> 08's undocumented-PII check; notes left mostly null -> 06.01;
-- full_name nullable but always populated -> 06.05; search_vector has no
-- GIN/GiST index (04.01) and no generated-column/trigger sync mechanism (04.02).
CREATE TABLE customers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id int NOT NULL,
    email text NOT NULL,
    full_name text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    search_vector tsvector
);

-- serial PK (mixed type family, and schema-drift type mismatch on the "id"
-- concept -> 01.05/01.06); customer_id is FK-shaped with no FK constraint
-- declared -> 01.04; "createdAt" is a naming-drift variant of
-- customers.created_at -> 01.05; attrs carries jsonb key-naming + value-type
-- drift with no validation layer and no GIN index (category 2, 03.02).
CREATE TABLE orders (
    id serial PRIMARY KEY,
    customer_id uuid,
    "createdAt" timestamptz,
    attrs jsonb,
    total numeric
);

-- No primary key at all -> 01.06; RLS enabled with zero policies attached
-- (a common misconfiguration, distinct from 07.03's "never attempted") ->
-- 08.02; user_id has an FK constraint that was created NOT VALID and never
-- validated -> 06.03; left with heavy dead-tuple bloat and no per-table
-- autovacuum tuning or recent vacuum -> 07.04/10.03.
CREATE TABLE sessions (
    session_token text,
    user_id uuid,
    payload jsonb
);

-- sku is behaviorally unique with no unique constraint enforcing it ->
-- 06.04; spec gets a large incompressible blob on a handful of rows to force
-- real out-of-line TOAST storage -> 07.05; created_at matches the
-- audit-timestamp naming convention but has real gaps -> 06.06.
CREATE TABLE products (
    id serial PRIMARY KEY,
    sku text,
    spec jsonb,
    created_at timestamptz
);

-- ~100 customers across 3 tenants; notes populated ~10% of the time (high
-- null fraction); email left intentionally unconstrained (near-unique).
INSERT INTO customers (tenant_id, email, full_name, notes, created_at)
SELECT
    (g % 3) + 1,
    'user' || g || '@example.com',
    'Customer ' || g,
    CASE WHEN g % 10 = 0 THEN 'VIP - handle with care' ELSE NULL END,
    now() - (g || ' days')::interval
FROM generate_series(1, 100) g;

-- ~200 orders. attrs alternates between two key-naming variants of the same
-- concepts (discount_pct/discountPercent, gift_wrap/giftWrap) and mixes a
-- "price" key between JSON number and JSON string across rows.
INSERT INTO orders (customer_id, "createdAt", attrs, total)
SELECT
    (SELECT id FROM customers ORDER BY random() LIMIT 1),
    now() - (g || ' hours')::interval,
    (CASE
        WHEN g % 2 = 0 THEN jsonb_build_object('discount_pct', 10, 'gift_wrap', true)
        ELSE jsonb_build_object('discountPercent', 15, 'giftWrap', false)
    END) || jsonb_build_object(
        'price',
        CASE WHEN g % 5 = 0 THEN to_jsonb('19.99'::text) ELSE to_jsonb(19.99) END
    ),
    19.99 * (g % 5 + 1)
FROM generate_series(1, 200) g;

-- ~150 products with behaviorally-unique SKUs; ~10% missing created_at.
INSERT INTO products (sku, spec, created_at)
SELECT
    'SKU-' || g,
    jsonb_build_object('description', 'Widget number ' || g),
    CASE WHEN g % 10 = 0 THEN NULL ELSE now() - (g || ' hours')::interval END
FROM generate_series(1, 150) g;

-- Force real TOAST storage on a handful of rows: many distinct md5 hashes
-- concatenated together, incompressible enough that pglz can't shrink the
-- out-of-line footprint below the check's threshold.
UPDATE products
SET spec = spec || jsonb_build_object(
    'blob',
    (SELECT string_agg(md5(x::text || random()::text), '') FROM generate_series(1, 8000) x)
)
WHERE id <= 8;

-- ~300 sessions, half deleted without a vacuum ever running -> heavy
-- dead-tuple bloat on cluster-wide autovacuum defaults.
INSERT INTO sessions (session_token, user_id, payload)
SELECT
    'tok_' || g,
    (SELECT id FROM customers ORDER BY random() LIMIT 1),
    '{}'::jsonb
FROM generate_series(1, 300) g;

DELETE FROM sessions WHERE ctid IN (
    SELECT ctid FROM sessions ORDER BY random() LIMIT 150
);

-- NOT VALID: Postgres enforces this for new writes but has never confirmed
-- the rows already in the table satisfy it.
ALTER TABLE sessions
    ADD CONSTRAINT sessions_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES customers (id) NOT VALID;

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;

-- Never queried by the traffic-generation step in setup-synthetic-db.sh, so
-- idx_scan stays at 0 -> unused index.
CREATE INDEX idx_orders_customer_id ON orders (customer_id);

-- Redundant with the implicit orders_pkey index: same leading column ("id").
CREATE INDEX idx_orders_id_extra ON orders (id);

-- certification_id is FK-shaped (ends in _id, references certifications) but
-- deliberately has no declared FOREIGN KEY constraint -> Lot & Certification
-- Traceability's orphaned-link check (and, separately, category 1's general
-- FK-shaped-column check flags it too, from the generic angle).
CREATE TABLE certifications (
    id serial PRIMARY KEY,
    cert_number text NOT NULL
);

-- lot_number missing on ~14% of rows -> lot-columns-poorly-populated;
-- lot_number has intentional duplicates ("L-2024-DUP" reused) with no unique
-- constraint -> duplicate-lot-numbers; certification_id left NULL on ~12% of
-- rows with no FK constraint enforcing the link at all -> orphaned-lot-
-- certification-links; cert_data carries free-form JSONB with no CHECK
-- constraint or trigger -> ungoverned-certification-data.
CREATE TABLE production_lots (
    id serial PRIMARY KEY,
    lot_number text,
    certification_id int,
    cert_data jsonb
);

INSERT INTO certifications (cert_number)
SELECT 'MTC-' || g FROM generate_series(1, 40) g;

INSERT INTO production_lots (lot_number, certification_id, cert_data)
SELECT
    CASE
        WHEN g % 7 = 0 THEN NULL
        WHEN g % 11 = 0 THEN 'L-2024-DUP'
        ELSE 'L-2024-' || lpad(g::text, 4, '0')
    END,
    CASE WHEN g % 8 = 0 THEN NULL ELSE (g % 40) + 1 END,
    jsonb_build_object('issued_by', 'Acme Mill', 'grade', CASE WHEN g % 3 = 0 THEN 'A' ELSE 'B' END)
FROM generate_series(1, 120) g;

-- Refreshes planner statistics (pg_stats, pg_stat_user_tables) that several
-- category 6/7/10 checks depend on.
ANALYZE;
