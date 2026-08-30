-- =========================================================
-- 02_seed.sql
-- Deterministic seed data (setseed fixes the RNG so every
-- fresh `docker compose up` produces identical demo data).
-- =========================================================

SELECT setseed(0.42);

-- ---------------------------------------------------------
-- customers (30 rows)
-- ---------------------------------------------------------
INSERT INTO customers (name, email, phone, region, signup_date)
SELECT
    'Customer ' || i,
    'customer' || i || '@example.com',
    '+91-9' || LPAD((100000000 + i)::text, 9, '0'),
    (ARRAY['North','South','East','West','Central'])[1 + floor(random() * 5)::int],
    CURRENT_DATE - (floor(random() * 700))::int
FROM generate_series(1, 30) AS i;

-- ---------------------------------------------------------
-- products (20 rows across 5 categories)
-- ---------------------------------------------------------
INSERT INTO products (name, category, price, cost, in_stock)
SELECT
    category || ' Item ' || i,
    category,
    round((20 + random() * 480)::numeric, 2)                          AS price,
    round((10 + random() * 200)::numeric, 2)                          AS cost,
    floor(random() * 500)::int
FROM (
    SELECT i, (ARRAY['Electronics','Home & Kitchen','Apparel','Sports','Books'])[1 + (i % 5)] AS category
    FROM generate_series(1, 20) AS i
) sub;

-- ---------------------------------------------------------
-- employees (15 rows across 4 departments)
-- ---------------------------------------------------------
INSERT INTO employees (name, department, role, salary, hire_date)
SELECT
    'Employee ' || i,
    dept,
    CASE WHEN i % 5 = 0 THEN 'Manager' ELSE 'Associate' END,
    round((45000 + random() * 90000)::numeric, 2),
    CURRENT_DATE - (floor(random() * 1500))::int
FROM (
    SELECT i, (ARRAY['Engineering','Sales','Marketing','Operations'])[1 + (i % 4)] AS dept
    FROM generate_series(1, 15) AS i
) sub;

-- ---------------------------------------------------------
-- orders (180 rows over the last 6 months)
-- ---------------------------------------------------------
INSERT INTO orders (customer_id, order_date, status)
SELECT
    1 + floor(random() * 30)::int,
    CURRENT_DATE - (floor(random() * 180))::int,
    (ARRAY['completed','completed','completed','pending','cancelled','refunded'])[1 + floor(random() * 6)::int]
FROM generate_series(1, 180);

-- ---------------------------------------------------------
-- order_items (1-4 independently randomized line items per order)
-- ---------------------------------------------------------
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT
    o.id,
    1 + floor(random() * 20)::int              AS product_id,
    1 + floor(random() * 4)::int                AS quantity,
    round((20 + random() * 480)::numeric, 2)    AS unit_price
FROM orders o
CROSS JOIN LATERAL generate_series(1, 1 + floor(random() * 3)::int) AS item_no;

ANALYZE customers;
ANALYZE products;
ANALYZE employees;
ANALYZE orders;
ANALYZE order_items;
