# =============================================================================
# ReelForge web (Next.js 15 App Router) image — NEW file for docker-compose.full.yml.
#
# Built with the repo ROOT as context (`context: .`) so this Dockerfile lives
# INSIDE the build context (compose forbids a dockerfile above its context) while
# still only pulling files from web/. The sibling ops/web.Dockerfile.dockerignore
# trims the context to just what the web build needs (BuildKit prefers a
# `<dockerfile>.dockerignore` over the context-root .dockerignore).
#
# This does NOT touch web/** — it only COPIES from it at build time.
# =============================================================================
FROM node:20-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# --- deps: install from the lockfile for reproducible builds -----------------
FROM base AS deps
COPY web/package.json web/package-lock.json ./
RUN npm ci

# --- build: compile the Next.js production bundle ----------------------------
FROM base AS build
# NEXT_PUBLIC_* must be present at build time (Next inlines them into the client
# bundle). Passed as build args from docker-compose.full.yml.
ARG NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_APP_API_KEY
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_APP_API_KEY=$NEXT_PUBLIC_APP_API_KEY \
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
RUN npm run build

# --- runtime: serve the built app with `next start` --------------------------
FROM base AS runtime
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# Copy the full built app (non-standalone build) plus its production deps.
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
