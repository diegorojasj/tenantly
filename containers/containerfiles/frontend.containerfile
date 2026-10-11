# Production frontend: build once, run the emitted Node server.
FROM node:20-slim AS build
ENV PNPM_HOME="/pnpm" PATH="/pnpm:$PATH" CI=true
RUN corepack enable
WORKDIR /app
COPY . /app
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile --store-dir /pnpm/store \
 && pnpm build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY --from=build /app/dist /app/dist
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/package.json /app/package.json
EXPOSE 3000
CMD ["node", "dist/server/node.js"]
