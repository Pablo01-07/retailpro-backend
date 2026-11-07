
DO
$do$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE  rolname = 'retailpro_app') THEN
      CREATE ROLE retailpro_app WITH LOGIN PASSWORD 'retailpro_app_pwd_2026';
   END IF;
END
$do$;

DO
$do$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE  rolname = 'powerbi_reader') THEN
      CREATE ROLE powerbi_reader WITH LOGIN PASSWORD 'powerbi_reader_pwd_2026';
   END IF;
END
$do$;

GRANT CONNECT ON DATABASE retailpro_db TO retailpro_app;
GRANT CONNECT ON DATABASE retailpro_db TO powerbi_reader;

GRANT USAGE, CREATE ON SCHEMA public TO retailpro_app;
GRANT USAGE ON SCHEMA public TO powerbi_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO retailpro_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO retailpro_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO powerbi_reader;
