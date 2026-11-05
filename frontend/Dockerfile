# Development image. Source is bind-mounted; node_modules lives in the image and
# an anonymous volume, so Linux native packages never mix with the Windows host.
FROM node:24.22.2-trixie-slim@sha256:54f84b4cf8432b21aaffd5d3ce8d41e12cea0d10d33c09d2f3c9879d49d6b446

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
