FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_ADOBE_EXPRESS_ENABLED=false
ARG NEXT_PUBLIC_ADOBE_EXPRESS_CLIENT_ID=
ARG NEXT_PUBLIC_ADOBE_EXPRESS_APP_NAME=BrandForge
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_ADOBE_EXPRESS_ENABLED=$NEXT_PUBLIC_ADOBE_EXPRESS_ENABLED \
    NEXT_PUBLIC_ADOBE_EXPRESS_CLIENT_ID=$NEXT_PUBLIC_ADOBE_EXPRESS_CLIENT_ID \
    NEXT_PUBLIC_ADOBE_EXPRESS_APP_NAME=$NEXT_PUBLIC_ADOBE_EXPRESS_APP_NAME
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 10001 brandforge \
    && adduser --system --uid 10001 --ingroup brandforge brandforge
COPY --from=builder --chown=brandforge:brandforge /app/public ./public
COPY --from=builder --chown=brandforge:brandforge /app/.next/standalone ./
COPY --from=builder --chown=brandforge:brandforge /app/.next/static ./.next/static
USER brandforge
EXPOSE 3000
CMD ["node", "server.js"]
