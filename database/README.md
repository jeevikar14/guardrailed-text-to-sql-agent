# Database Setup

This directory contains the PostgreSQL initialization scripts used by the
`postgres` service in `docker-compose.yml`.

## How it works

Postgres's official Docker image automatically executes every `.sql` file in
`/docker-entrypoint-initdb.d/` **in filename order**, but **only on first
container start** (i.e., when the `pgdata` volume is empty).

| File | Purpose |
|---|---|
| `init/01_schema.sql` | Creates `customers`, `products`, `orders`, `order_items`, `employees` |
| `init/02_seed.sql` | Populates deterministic demo data (`setseed(0.42)`) |
| `init/03_readonly_user.sql` | Creates the `app_readonly` role used by the Safe Executor |

## Two database roles

| Role | Used by | Privileges |
|---|---|---|
| `app_admin` (`POSTGRES_USER`) | Schema introspection, admin scripts | Full owner privileges |
| `app_readonly` | **Safe Executor only** (actual NL-query execution) | `SELECT`-only, no `INSERT`/`UPDATE`/`DELETE`/DDL, 10s statement timeout, capped connections |

The read-only role is the real security boundary. Guardrails validate SQL
*before* execution, but even a guardrail bypass cannot mutate data, because
the executing role is physically incapable of it.

## Resetting the database

Since init scripts only run once, to pick up schema/seed changes you must
drop the volume:

```bash
docker compose down -v
docker compose up --build
```

## Connecting manually

```bash
docker exec -it text2sql-postgres psql -U app_admin -d text2sql
```

To verify the read-only role is actually locked down:

```bash
docker exec -it text2sql-postgres psql -U app_readonly -d text2sql \
  -c "DELETE FROM customers WHERE id = 1;"
# Expected: ERROR: permission denied for table customers
```
