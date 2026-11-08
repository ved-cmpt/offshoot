# Development image. Source is bind-mounted; node_modules lives in the image and
# an anonymous volume, so Linux native packages never mix with the Windows host.
FROM node:26.13.0-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072

ENV NG_CLI_ANALYTICS=false

WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --no-audit --no-fund \
    && mkdir -p .angular dist
COPY --chown=node:node . .

EXPOSE 4200
CMD ["npm", "start"]
