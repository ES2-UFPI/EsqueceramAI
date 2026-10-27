FROM nginx:alpine

# Copia os arquivos estáticos para o diretório padrão do Nginx
COPY index.html styles.css app.js /usr/share/nginx/html/

# Copia a configuração do Nginx com proxy /api para o backend
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
