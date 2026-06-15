# Frontend image for ROGUE — Next.js 16 production build.
# Built by docker-compose.full.yml (§A.27) with context=./frontend.
# Two-stage to keep the runtime image small: build then copy.
#
# NOTE Day 3: for the smallest possible image, set `output: 'standalone'`
# in `frontend/next.config.ts` and switch the second stage to copy from
# `.next/standalone` + `.next/static` (per Next.js 16 standalone deploy guide).

FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . ./

# Self-host renders against a live LOCAL backend that's only up at RUNTIME (not during this image
# build), so prerendering the API-backed dashboard pages here would bake in the "API unavailable"
# placeholder and ISR would keep serving it. Flip those pages to force-dynamic (per-request render)
# for the self-host image ONLY — Vercel builds skip this Dockerfile and keep ISR ("auto"). `dynamic`
# must be a static string literal (Next 16 rejects an expression), so we rewrite the literal here.
RUN sed -i 's/export const dynamic = "auto";/export const dynamic = "force-dynamic";/' \
      src/app/matrix/page.tsx src/app/feed/page.tsx src/app/brief/page.tsx src/app/page.tsx

RUN npm run build

FROM node:20-alpine

WORKDIR /app

# Copy only the build artifacts + the runtime deps we actually need.
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

EXPOSE 3000

CMD ["npm", "run", "start"]
