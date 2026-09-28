FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
