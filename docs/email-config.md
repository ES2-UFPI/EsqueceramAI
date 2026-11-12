# Envio de e-mail em produção

O backend envia dois tipos de mensagem: o **código de confirmação de retirada** (US05)
e o **aviso de correspondência** (US09). O transporte é SMTP puro, em
`application/delivery/email_service.py`.

## A limitação do Render

Instâncias **gratuitas** do Render não fazem saída de rede nas portas `25`, `465` e
`587` ([docs](https://render.com/docs/free)). Como `smtplib` usa essas portas por
padrão, o envio falha com:

```
[Errno 101] Network is unreachable
```

Não é credencial errada nem host inexistente — é bloqueio de rede. A porta `25` é
bloqueada em **todas** as instâncias, inclusive nas pagas.

## Configuração que funciona no plano gratuito

Use a porta **2525**, que não está na lista de bloqueio. Entre os provedores gratuitos:

| Provedor | Host | Porta | Limite gratuito |
|---|---|---|---|
| Brevo | `smtp-relay.brevo.com` | 2525 | 300/dia |
| Mailjet | `in-v3.mailjet.com` | 2525 | 200/dia |
| Mailgun | `smtp.mailgun.org` | 2525 | limitado |

Variáveis no serviço do Render (Environment):

```dotenv
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=2525
SMTP_USER=<login SMTP do provedor>
SMTP_PASSWORD=<chave SMTP do provedor>
SMTP_FROM=Esqueceram AI <no-reply@seu-dominio-verificado>
SMTP_STARTTLS=true
```

O `SMTP_PORT` do `render.yaml` já vem `2525`. As demais são `sync: false`, ou seja,
precisam ser preenchidas no painel — e o painel **vence** o `render.yaml` para
variáveis que já existem no serviço.

`SMTP_FROM` precisa ser um remetente verificado no provedor, senão a mensagem é
recusada mesmo com a porta liberada.

## Alternativa: API HTTP

Provedores por HTTP (Resend, Brevo, SendGrid) usam a porta 443 e não sofrem o
bloqueio. Exigiria um transporte novo em `email_service.py`; a opção escolhida foi
manter o SMTP e só trocar a porta.

## Diagnóstico

Quando o erro é `Network is unreachable` numa das portas bloqueadas, o log já aponta
o motivo e a alternativa:

```
A porta 587 é bloqueada para saída nas instâncias gratuitas do Render.
Use SMTP_PORT=2525 (Brevo, Mailgun e Mailjet aceitam) ou um provedor por HTTP.
```

Sem `SMTP_HOST` definido, a aplicação entra em **modo console**: a mensagem é impressa
no log em vez de enviada. Os fluxos continuam funcionando, mas ninguém recebe o e-mail.
