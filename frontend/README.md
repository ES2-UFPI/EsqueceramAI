# Frontend estático

Este diretório é a publicação do GitHub Pages. Não exige Node, build ou acesso
direto ao banco: `app.js` chama somente a API Flask publicada no Render.

Em GitHub Pages, a constante `API` usa por padrão
`https://esqueceramai.onrender.com/api`. Para outro serviço Render, inclua
antes de `app.js` em `index.html`:

```html
<script>window.ESQUECERAM_API = "https://sua-api.onrender.com/api";</script>
```

Configure a mesma URL do Pages em `FRONTEND_ORIGIN` (ou `CORS_ORIGINS`) no
Render. A service role do Supabase jamais deve ser adicionada a este diretório.
