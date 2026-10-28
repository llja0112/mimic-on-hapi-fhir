# Deploying to Render or Railway with Neon Postgres

HAPI FHIR runs on Render or Railway; the database is a Neon Postgres project.
All environments build [hapi/Dockerfile](hapi/Dockerfile), which pins the HAPI
version and adds [hapi/application.yaml](hapi/application.yaml). Only the Neon
credentials differ, passed as environment variables.

> **Data licensing.** The MIMIC-IV FHIR **demo** is ODbL and may be served
> publicly. Full MIMIC-IV is credentialed: its DUA forbids sharing, so it must
> never be loaded into a publicly reachable server.

## 1. Create the Neon database

1. Create a Neon project on **Postgres 16**, in the same region as your app
   (e.g. AWS us-east-1 for Render `virginia` / Railway US East).
2. Copy the **direct** connection details (host without `-pooler`). HAPI pools
   its own connections and is safer without PgBouncer transaction mode.
3. Build the three variables (also in [.env.example](.env.example)):
   ```
   SPRING_DATASOURCE_URL=jdbc:postgresql://ep-xxxx.us-east-1.aws.neon.tech/neondb?sslmode=require
   SPRING_DATASOURCE_USERNAME=neondb_owner
   SPRING_DATASOURCE_PASSWORD=...
   ```
   Keep only `?sslmode=require`; drop `channel_binding=require` from Neon's
   copied string.
4. Optional: create a Neon branch before loading so you can reset to it.

Do **not** run [postgres-init.sql](postgres-init.sql) on Neon (`ALTER SYSTEM`
and server settings are not allowed there).

## 2. Load the data into Neon (from your machine)

Put the NDJSON files in `./input_data/fhir` (gitignored), then run HAPI locally
against Neon and use the existing bulk importer:

```bash
cp .env.example .env    # fill in the SPRING_DATASOURCE_* values
docker compose -f docker-compose.neon.yml up -d --build
curl -f http://localhost:8080/fhir/metadata    # wait until this succeeds

python bulk_import.py \
    --fhir-url http://localhost:8080/fhir \
    --file-server-url http://fhir-files:8000

curl "http://localhost:8080/fhir/Patient?_summary=count"
docker compose -f docker-compose.neon.yml down
```

The first startup creates HAPI's schema in Neon and can take a few minutes.
Stop the local stack after loading so only the deployed server uses the database.

Check how much storage the load used (to pick a Neon plan):
```sql
SELECT pg_size_pretty(pg_database_size('neondb'));
```

**Alternative:** load into the local Postgres stack (`docker compose up`) and
copy it over. The local HAPI must be the same version as `hapi/Dockerfile`.
```bash
pg_dump -Fc --no-owner --no-acl -h localhost -U postgres postgres > hapi.dump
pg_restore --no-owner --no-acl -d "postgresql://neondb_owner:...@ep-xxxx.../neondb?sslmode=require" hapi.dump
```

## 3a. Deploy on Render

1. Push this repo to GitHub, then in Render choose **New > Blueprint** and select
   it. [render.yaml](render.yaml) defines one Docker web service (Standard plan,
   ~2 GB RAM; HAPI runs out of memory on smaller plans).
2. Enter the three `SPRING_DATASOURCE_*` values when prompted.
3. Check `https://<service>.onrender.com/fhir/metadata`.

## 3b. Deploy on Railway

1. **New Project > Deploy from GitHub repo**, select this repo.
2. In the service **Settings**: set **Root Directory** to `/hapi` and
   **Config-as-code file** to `/hapi/railway.json` (Dockerfile build, health
   check on `/fhir/metadata`).
3. In **Variables**, add `PORT=8080` and the three `SPRING_DATASOURCE_*` values.
4. Under **Networking**, generate a public domain and check `/fhir/metadata`.
   Give the service at least 2 GB of memory.

## 4. After deploying

- `$import` is disabled on deployed instances (`bulk_import_enabled: false`).
- The server has no authentication: anyone with the URL can create, update or
  delete resources. Acceptable for the demo; for anything else put it behind an
  authenticating proxy (e.g. Cloudflare Access) or keep it private.
- HAPI's background jobs keep the Neon compute awake while the app runs, so
  watch compute hours on Neon's free plan.
