FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY *.mjs ./

USER node

CMD ["node", "server.mjs"]
