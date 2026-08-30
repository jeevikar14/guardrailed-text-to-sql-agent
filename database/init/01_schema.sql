-- =========================================================
-- 01_schema.sql
-- Core schema for the Text-to-SQL Guardrails demo database.
--
-- Design notes:
--   - customers.email / customers.phone   -> PII (policy: blocked)
--   - employees.salary                    -> CONFIDENTIAL (policy: blocked)
--   - Everything else is intentionally safe to expose, so the
--     guardrail tests have clear "should pass" vs "should block" cases.
-- =========================================================

CREATE TABLE IF NOT EXISTS customers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(120)  NOT NULL,
    email           VARCHAR(150)  NOT NULL UNIQUE,      -- PII
    phone           VARCHAR(30),                        -- PII
    region          VARCHAR(60)   NOT NULL,
    signup_date     DATE          NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(150)  NOT NULL,
    category        VARCHAR(80)   NOT NULL,
    price           NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    cost            NUMERIC(10, 2) NOT NULL CHECK (cost >= 0),  -- CONFIDENTIAL (margin data)
    in_stock        INTEGER       NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER       NOT NULL REFERENCES customers(id),
    order_date      DATE          NOT NULL DEFAULT CURRENT_DATE,
    status          VARCHAR(30)   NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('completed', 'pending', 'cancelled', 'refunded'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER       NOT NULL REFERENCES orders(id),
    product_id      INTEGER       NOT NULL REFERENCES products(id),
    quantity        INTEGER       NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE IF NOT EXISTS employees (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(120)  NOT NULL,
    department      VARCHAR(80)   NOT NULL,
    role            VARCHAR(80)   NOT NULL,
    salary          NUMERIC(10, 2) NOT NULL,             -- CONFIDENTIAL
    hire_date       DATE          NOT NULL DEFAULT CURRENT_DATE
);

-- Indexes to keep demo queries fast and joins realistic
CREATE INDEX IF NOT EXISTS idx_orders_customer_id      ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date        ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id      ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id    ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_products_category          ON products(category);
CREATE INDEX IF NOT EXISTS idx_customers_region            ON customers(region);
CREATE INDEX IF NOT EXISTS idx_employees_department         ON employees(department);

COMMENT ON TABLE customers   IS 'Customer records. email and phone are PII and must not be exposed via NL queries.';
COMMENT ON TABLE products    IS 'Product catalog. cost is confidential margin data.';
COMMENT ON TABLE orders      IS 'Customer orders, one row per order.';
COMMENT ON TABLE order_items IS 'Line items per order, links orders to products.';
COMMENT ON TABLE employees   IS 'Internal employee records. salary is confidential.';
