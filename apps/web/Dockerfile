FROM node:24-alpine

WORKDIR /app

RUN npm install --global npm@11.6.0

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
