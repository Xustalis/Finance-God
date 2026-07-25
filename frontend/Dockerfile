FROM node:20-alpine

WORKDIR /app

# 使用 lockfile + npm ci 保证开发容器依赖可复现。
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

USER node

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
