# Development image. Source is bind-mounted; node_modules lives in the image and
# an anonymous volume, so Linux native packages never mix with the Windows host.
FROM node:24.22.2-trixie-slim@sha256:0820eaa85e07d0490446dd01d14707e17e6108a36988cf374899cd057eb3812d

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
