FROM node:20-alpine AS build
WORKDIR /workspace
COPY package.json package-lock.json ./
COPY apps/web ./apps/web
COPY apps/mobile/package.json ./apps/mobile/package.json
COPY packages ./packages
RUN npm ci
RUN npm run shared:build
RUN npm --workspace reelforge-web run build

FROM node:20-alpine AS runtime
WORKDIR /workspace
ENV NODE_ENV=production
COPY --from=build /workspace/package.json /workspace/package-lock.json ./
COPY --from=build /workspace/node_modules ./node_modules
COPY --from=build /workspace/apps/web ./apps/web
COPY --from=build /workspace/packages ./packages
EXPOSE 3000
CMD ["npm", "--workspace", "reelforge-web", "run", "start"]
