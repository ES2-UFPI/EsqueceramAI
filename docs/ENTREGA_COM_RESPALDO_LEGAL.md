# Entrega com respaldo legal (checkout no posto de coleta)

> **História de usuário:** Como atendente do posto de coleta, quero registrar a entrega do objeto com o CPF e
> documento com foto do retirante para ter respaldo legal caso o item seja contestado posteriormente.

Todo o módulo vive em `app/delivery/` e em tabelas novas; o código existente só recebeu ganchos mínimos
(veja "O que mudou no código existente").

## Critérios de aceitação → código → teste

| Critério | Onde está | Teste |
| --- | --- | --- |
| Validar formato e dígito verificador do CPF | `app/delivery/cpf.py` (usado em `service.start_delivery`) | `tests/test_cpf.py`, `test_delivery_service.py::test_cpf_and_form_validation` |
| Upload ou captura da imagem do documento com foto | `app/delivery/documents.py`, `templates/delivery/new.html`, `static/delivery.js` | `tests/test_delivery_documents.py`, `test_delivery_web.py::test_checkout_form_renders_with_all_fields` |
| Confirmação por código enviado ao e-mail do retirante | `app/delivery/security.py`, `email_service.py`, `service.confirm_delivery` | `tests/test_delivery_email_security.py`, `test_delivery_service.py` (fluxo, bloqueio, expiração, reenvio) |
| Recibo/termo digital em PDF (data/hora, CPF mascarado, item, matrícula do atendente) | `app/delivery/receipt.py` | `tests/test_delivery_receipt.py`, `test_delivery_service.py::test_full_flow_receipt_and_item_returned` |
| Formulário de checkout restrito ao atendente do posto | `app/delivery/web.py` (`login_required("OPERATOR_POST")`), `api.py` | `test_delivery_web.py::test_checkout_pages_restricted_to_attendant`, `test_delivery_service.py::test_only_attendant_can_checkout` |

## Fluxo

1. O atendente (`OPERATOR_POST`, com matrícula cadastrada) abre **Entregas → Nova entrega**.
2. Informa item, nome, **CPF**, **e-mail** do retirante e anexa/captura a foto do **documento**.
3. O sistema valida tudo, grava a entrega como `PENDING` e envia um **código de 6 dígitos** ao e-mail.
4. O retirante lê o código; o atendente o digita. Código correto → o **termo em PDF** é gerado e gravado,
   e o item passa a `RETURNED` pelo fluxo já existente (pontos, notificações e devolução do item correspondente).

## Decisões de segurança e LGPD

- **CPF completo não é guardado.** Persistimos a máscara (`***.982.247-**`) e um **HMAC** do CPF. Numa
  contestação, `POST /api/deliveries/:id/verify` confere um CPF apresentado sem expor o dado. A imagem do
  documento (que contém o CPF) fica em acesso restrito.
- **Código de confirmação**: aleatório (`secrets`), só o HMAC (vinculado à entrega) é salvo; vale 15 min;
  5 tentativas e a entrega é cancelada; reenvio com intervalo de 60 s e no máximo 3; uso único.
- **Imagem do documento**: valida a assinatura real do arquivo (JPG/PNG/WebP, até 5 MB), calcula SHA-256
  (impresso no termo) e só é servida a quem tem acesso à entrega, com `Cache-Control: no-store`.
- **Termo imutável**: o PDF é gravado uma vez, com código de verificação (HMAC) que revela adulteração.
  Dados de item, ponto e atendente são copiados para a entrega (snapshot): o termo sobrevive à exclusão do item.
- **Linha do tempo pública do item** registra apenas o nº do termo (sem nome nem CPF).
- **Perfis**: só `OPERATOR_POST` registra/confirma/cancela. `ADMIN` consulta e audita. Comunidade não tem acesso.
- **Chave**: defina `DELIVERY_HMAC_KEY` (ou `SECRET_KEY`) forte e estável. Se mudar, códigos pendentes e a
  conferência de CPF de entregas antigas deixam de funcionar.

## Configuração

Veja `.env.example`. Sem `SMTP_HOST`, o e-mail é **impresso no console do servidor** (modo desenvolvimento);
o código nunca aparece na tela. Para enviar de verdade, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM` (STARTTLS por padrão; `SMTP_SSL=true` para porta 465).

`DELIVERY_REQUIRE_CHECKOUT=true` (opcional) faz o botão rápido "Devolvido" ser recusado (409) para itens
encontrados em ponto de coleta, obrigando o uso do formulário com termo. Por padrão fica desligado.

## API

| Método | Endpoint |
| --- | --- |
| GET / PUT | `/api/attendant/registration` (matrícula do atendente, única) |
| GET / POST | `/api/deliveries` (POST: `multipart/form-data` com `itemId`, `recipientName`, `cpf`, `email`, `document`) |
| GET | `/api/deliveries/:id` (detalhe + trilha de auditoria) |
| POST | `/api/deliveries/:id/confirm` · `/resend` · `/cancel` · `/verify` |
| GET | `/api/deliveries/:id/receipt` (PDF) · `/api/deliveries/:id/document` (imagem) |

## O que mudou no código existente (mínimo)

| Arquivo | Mudança |
| --- | --- |
| `app/__init__.py` | 2 linhas: `delivery.init_app(app)` |
| `app/services/seed_service.py` | matrícula demo do operador; correção do seed em banco vazio (commit próprio) |
| `app/api/routes.py` | 1 linha: `enforce_checkout_policy` (inativa por padrão) |
| `app/web/templates/app_base.html`, `item_detalhe.html`, `painel_operador.html` | link no menu e botões "Registrar entrega" |
| `requirements.txt`, `.env.example` | `reportlab`; variáveis de e-mail e política |

Nenhuma coluna de tabela existente foi alterada: `create_all` cria só as tabelas novas (`attendant_profiles`,
`deliveries`, `delivery_documents`, `delivery_receipts`, `delivery_events`), sem migração.

## Testes

```bash
pip install -r requirements-dev.txt
pytest          # usa um SQLite temporário; não toca no seu banco
```

## Limitações conhecidas

- Não há política de retenção/expurgo (LGPD) das imagens de documento; defina o prazo com o jurídico.
- O termo tem carimbo de tempo do servidor e código HMAC, mas **não é assinatura digital ICP-Brasil**.
- A captura por câmera do navegador exige HTTPS (ou localhost); sem isso, usa o seletor nativo/upload.
- Os formulários seguem o padrão do projeto (cookie `SameSite=Lax`, sem token CSRF dedicado).
