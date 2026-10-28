# HAPI FHIR configured for Neon Postgres.
# Used by docker-compose.neon.yml, render.yaml and Railway so every environment
# runs the same HAPI version against the same database schema.
FROM hapiproject/hapi:v8.12.0-2

# Spring Boot loads ./config/application.yaml (WORKDIR is /app) on top of the
# image's built-in config. Datasource URL/credentials come from env vars.
COPY application.yaml /app/config/application.yaml

# The image is distroless and ignores JAVA_OPTS; the JVM reads JAVA_TOOL_OPTIONS.
# Size the heap from the container's memory limit instead of a fixed -Xmx.
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+UseG1GC"

EXPOSE 8080
