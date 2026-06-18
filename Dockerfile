FROM node:20-slim

WORKDIR /app

COPY node-server/package*.json ./node-server/
RUN cd node-server && npm install --omit=dev

COPY node-server ./node-server

ENV PORT=8000
EXPOSE 8000

CMD ["node", "node-server/index.js"]
