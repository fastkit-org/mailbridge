# MailBridge 📧

[![CI](https://github.com/fastkit-org/mailbridge/actions/workflows/tests.yml/badge.svg)](https://github.com/fastkit-org/mailbridge/actions/workflows/tests.yml)
[![PyPI version](https://img.shields.io/pypi/v/mailbridge.svg)](https://pypi.org/project/mailbridge/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Unified Python email library with multi-provider support**

**MailBridge** is a flexible Python library for sending emails, allowing you to use multiple providers through a single, simple interface. It supports **SMTP**, **SendGrid**, **Mailgun**, **Amazon SES**, **Postmark**, and **Brevo** — with both synchronous and asynchronous APIs.

---

## ✨ Features

- 🎨 **Template Support** — Use dynamic templates with all major providers
- 📎 **Attachment Support** — Add file attachments to any email
- 📦 **Bulk Sending** — Send thousands of emails efficiently with native API optimizations
- ⚡ **Async Support** — First-class `async/await` API via `AsyncMailBridge`
- 🔧 **Unified Interface** — Same code works with any provider
- ✅ **Fully Tested** — 220+ unit tests, 92% coverage
- 🚀 **Production Ready** — Battle-tested and reliable
- 📚 **Great Documentation** — Extensive examples and guides

---

## 📦 Installation

MailBridge uses [uv](https://docs.astral.sh/uv/) for dependency management. If you don't have `uv` installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installing the package

```bash
# Core install (SMTP, SendGrid, Mailgun, Postmark, Brevo work out of the box)
uv add mailbridge

# With async support (aiohttp + aiosmtplib)
uv add "mailbridge[async]"

# With Amazon SES support
uv add "mailbridge[ses]"

# Everything
uv add "mailbridge[all]"
```

### pip (alternative)

```bash
pip install mailbridge
pip install "mailbridge[async]"   # async support
pip install "mailbridge[ses]"     # Amazon SES
pip install "mailbridge[all]"     # everything
```

---

## 🚀 Quick Start

### Synchronous

```python
from mailbridge import MailBridge

mailer = MailBridge(provider='sendgrid', api_key='your-api-key')

response = mailer.send(
    to='recipient@example.com',
    subject='Hello from MailBridge!',
    body='<h1>It works!</h1><p>Email sent successfully.</p>'
)

print(f"Sent! Message ID: {response.message_id}")
```

### Asynchronous

```python
import asyncio
from mailbridge import AsyncMailBridge

async def main():
    async with AsyncMailBridge(provider='sendgrid', api_key='your-api-key') as mailer:
        response = await mailer.send(
            to='recipient@example.com',
            subject='Hello from MailBridge!',
            body='<h1>It works!</h1><p>Email sent successfully.</p>'
        )
        print(f"Sent! Message ID: {response.message_id}")

asyncio.run(main())
```

---

## ⚡ AsyncMailBridge

`AsyncMailBridge` mirrors the `MailBridge` API exactly — every method that exists on the sync client has an `await`-able counterpart on the async client. Both clients share the same provider registry, so `register_provider` works for both.

### When to use the async client

Use `AsyncMailBridge` whenever your application already runs an event loop — FastAPI, Starlette, Sanic, or any other async framework. Firing email sends with `await` means the event loop is never blocked, and bulk sends run all requests concurrently.

### Single email

```python
import asyncio
from mailbridge import AsyncMailBridge

async def send_welcome(user_email: str, user_name: str):
    async with AsyncMailBridge(provider='sendgrid', api_key='SG.xxxxx') as mailer:
        return await mailer.send(
            to=user_email,
            subject='Welcome!',
            template_id='d-welcome-template',
            template_data={'name': user_name}
        )

asyncio.run(send_welcome('user@example.com', 'Alice'))
```

### Bulk sending

```python
import asyncio
from mailbridge import AsyncMailBridge, EmailMessageDto

async def send_newsletter(subscribers: list[dict]):
    messages = [
        EmailMessageDto(
            to=sub['email'],
            template_id='newsletter-template',
            template_data={'name': sub['name']}
        )
        for sub in subscribers
    ]

    async with AsyncMailBridge(provider='sendgrid', api_key='SG.xxxxx') as mailer:
        result = await mailer.send_bulk(messages)

    print(f"Sent: {result.successful}/{result.total}, Failed: {result.failed}")

asyncio.run(send_newsletter([...]))
```

Bulk sends fire all requests **concurrently** via `asyncio.gather` — for HTTP providers (SendGrid, Mailgun, Brevo, Postmark) this means one `aiohttp.ClientSession` is shared across all concurrent requests. SMTP bulk sends reuse a single async SMTP connection for the entire batch.

### FastAPI integration

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from mailbridge import AsyncMailBridge

mailer: AsyncMailBridge | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mailer
    mailer = AsyncMailBridge(provider='sendgrid', api_key='SG.xxxxx')
    yield
    await mailer.close()

app = FastAPI(lifespan=lifespan)

@app.post("/register")
async def register(email: str, name: str):
    await mailer.send(
        to=email,
        subject='Welcome!',
        template_id='d-welcome-template',
        template_data={'name': name}
    )
    return {"status": "ok"}
```

### Async vs sync — which to choose?

| | `MailBridge` | `AsyncMailBridge` |
|---|---|---|
| API style | Synchronous | `async/await` |
| Best for | Scripts, Django, Flask | FastAPI, Starlette, asyncio apps |
| Bulk concurrency | Sequential | Concurrent (`asyncio.gather`) |
| SES (boto3) | Direct call | Thread pool (boto3 has no async SDK) |
| Requires `[async]` extra | No | Yes (for native I/O) |

> **Note:** `AsyncMailBridge` works without the `[async]` extra — it falls back to a thread pool executor for all providers. Install `mailbridge[async]` to get native non-blocking I/O via `aiohttp` and `aiosmtplib`.

---

## 🎯 Supported Providers

| Provider | Templates | Bulk API | Async I/O |
|----------|-----------|----------|-----------|
| **SendGrid** | ✅ | ✅ Native | ✅ `aiohttp` |
| **Amazon SES** | ✅ | ✅ Native | ✅ Thread pool |
| **Postmark** | ✅ | ✅ Native | ✅ `aiohttp` |
| **Mailgun** | ✅ | ✅ Native | ✅ `aiohttp` |
| **Brevo** | ✅ | ✅ Native | ✅ `aiohttp` |
| **SMTP** | ❌ | ❌ | ✅ `aiosmtplib` |

---

## 📖 Provider Setup

### SendGrid

```python
from mailbridge import MailBridge

mailer = MailBridge(
    provider='sendgrid',
    api_key='SG.xxxxx',
    from_email='noreply@yourdomain.com'
)
```

- [Get API Key](https://app.sendgrid.com/settings/api_keys)
- [Documentation](https://docs.sendgrid.com/)

---

### Amazon SES

```python
mailer = MailBridge(
    provider='ses',
    aws_access_key_id='AKIAXXXX',
    aws_secret_access_key='xxxxx',
    region_name='us-east-1',
    from_email='verified@yourdomain.com'
)

# Or using IAM role (EC2/Lambda) — no credentials needed
mailer = MailBridge(
    provider='ses',
    region_name='us-east-1',
    from_email='verified@yourdomain.com'
)
```

- [SES Console](https://console.aws.amazon.com/ses/)
- [Documentation](https://docs.aws.amazon.com/ses/)

**Note:** Email addresses must be verified in sandbox mode. Request production access to send to any address.

---

### Postmark

```python
mailer = MailBridge(
    provider='postmark',
    server_token='xxxxx-xxxxx',
    from_email='verified@yourdomain.com',
    track_opens=True,
    track_links='HtmlAndText'
)
```

- [Get Token](https://account.postmarkapp.com/servers)
- [Documentation](https://postmarkapp.com/developer)

---

### Mailgun

```python
mailer = MailBridge(
    provider='mailgun',
    api_key='key-xxxxx',
    endpoint='https://api.mailgun.net/v3/mg.yourdomain.com',
    from_email='noreply@yourdomain.com'
)
```

- [Get API Key](https://app.mailgun.com/settings/api_security)
- [Documentation](https://documentation.mailgun.com/)

---

### Brevo

```python
mailer = MailBridge(
    provider='brevo',
    api_key='xkeysib-xxxxx',
    from_email='noreply@yourdomain.com'
)

# Template IDs are integers for Brevo
mailer.send(
    to='user@example.com',
    template_id=123,
    template_data={'name': 'Alice'}
)
```

- [Get API Key](https://app.brevo.com/settings/keys/api)
- [Documentation](https://developers.brevo.com/)

---

### SMTP

```python
# Gmail
mailer = MailBridge(
    provider='smtp',
    host='smtp.gmail.com',
    port=587,
    username='you@gmail.com',
    password='app-password',  # Use App Password, not your regular password
    use_tls=True
)

# Outlook
mailer = MailBridge(
    provider='smtp',
    host='smtp.office365.com',
    port=587,
    username='you@outlook.com',
    password='your-password',
    use_tls=True
)

# Custom server with SSL
mailer = MailBridge(
    provider='smtp',
    host='mail.yourdomain.com',
    port=465,
    username='user',
    password='pass',
    use_ssl=True
)
```

**Gmail:** Use an [App Password](https://support.google.com/accounts/answer/185833) (requires 2FA enabled).

---

## 💡 Common Use Cases

### Welcome Emails

```python
mailer.send(
    to=new_user.email,
    template_id='welcome-email',
    template_data={
        'name': new_user.name,
        'activation_link': generate_activation_link(new_user)
    }
)
```

### Password Reset

```python
mailer.send(
    to=user.email,
    template_id='password-reset',
    template_data={
        'reset_link': generate_reset_link(user),
        'expiry_hours': 24
    }
)
```

### Newsletters (Bulk, async)

```python
import asyncio
from mailbridge import AsyncMailBridge, EmailMessageDto

async def send_newsletter(subscribers):
    messages = [
        EmailMessageDto(
            to=sub.email,
            template_id='newsletter',
            template_data={
                'name': sub.name,
                'unsubscribe_link': generate_unsubscribe_link(sub)
            }
        )
        for sub in subscribers
    ]

    async with AsyncMailBridge(provider='sendgrid', api_key='SG.xxxxx') as mailer:
        result = await mailer.send_bulk(messages)

    print(f"Sent: {result.successful}/{result.total}")

asyncio.run(send_newsletter(subscribers))
```

### Transactional Notifications

```python
mailer.send(
    to=order.customer_email,
    template_id='order-confirmation',
    template_data={
        'order_number': order.id,
        'total': order.total,
        'items': order.items,
        'tracking_url': order.tracking_url
    }
)
```

---

## 🔧 Advanced Features

### Attachments

```python
from pathlib import Path

mailer.send(
    to='customer@example.com',
    subject='Your Invoice',
    body='<p>Please find your invoice attached.</p>',
    attachments=[
        Path('invoice.pdf'),
        ('report.csv', csv_bytes, 'text/csv'),  # (filename, bytes, mimetype)
    ]
)
```

### CC and BCC

```python
mailer.send(
    to='client@example.com',
    subject='Project Update',
    body='<p>Latest update...</p>',
    cc=['manager@company.com', 'team@company.com'],
    bcc=['archive@company.com']
)
```

### Custom Headers and Tags

```python
mailer.send(
    to='user@example.com',
    subject='Campaign Email',
    body='<p>Special offer!</p>',
    headers={'X-Campaign-ID': 'summer-2024'},
    tags=['marketing', 'campaign']
)
```

### Context Managers

```python
# Sync
with MailBridge(provider='smtp', host='...', port=587, ...) as mailer:
    mailer.send(to='user@example.com', subject='Test', body='...')
# Connection automatically closed

# Async
async with AsyncMailBridge(provider='sendgrid', api_key='...') as mailer:
    await mailer.send(to='user@example.com', subject='Test', body='...')
# Async connection automatically closed
```

### Custom Providers

```python
from mailbridge import MailBridge
from mailbridge.providers.base_email_provider import BaseEmailProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO

class MyProvider(BaseEmailProvider):
    def _validate_config(self):
        if 'api_key' not in self.config:
            raise ConfigurationError("Missing api_key")

    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        # Your implementation
        return EmailResponseDTO(success=True, provider='myprovider')

# Register once — available to both MailBridge and AsyncMailBridge
MailBridge.register_provider('myprovider', MyProvider)

mailer = MailBridge(provider='myprovider', api_key='...')
```

---

## 🧪 Development Setup

MailBridge uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and set up
git clone https://github.com/fastkit-org/mailbridge
cd mailbridge

# Create venv and install all dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run tests with coverage report
uv run pytest --cov=mailbridge --cov-report=html

# Linting and formatting
uv run black mailbridge tests
uv run isort mailbridge tests
uv run flake8 mailbridge
uv run mypy mailbridge
```

### Running specific test suites

```bash
# All tests
uv run pytest

# Sync provider tests only
uv run pytest tests/test_sendgrid_provider.py tests/test_mailgun_provider.py -v

# Async tests only
uv run pytest tests/test_sendgrid_async.py tests/test_mailgun_async.py \
               tests/test_brevo_async.py tests/test_postmark_async.py \
               tests/test_smtp_async.py tests/test_ses_async.py \
               tests/test_async_mailbridge_client.py -v

# Single file
uv run pytest tests/test_sendgrid_async.py -v
```

---

## 📊 Bulk Sending Performance

| Provider | Sync | Async |
|----------|------|-------|
| **SendGrid** | Native batch API | Concurrent via `asyncio.gather` |
| **SES** | 50-recipient batches | Concurrent thread pool |
| **Postmark** | Sequential | Concurrent via `asyncio.gather` |
| **Mailgun** | Sequential | Concurrent via `asyncio.gather` |
| **Brevo** | Native batch API | Native batch API async |
| **SMTP** | Single connection reuse | Single async connection reuse |

---

## 📄 License

MIT License — see [LICENSE](https://opensource.org/license/MIT) for details.

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/fastkit-org/mailbridge/issues)
- **Discussions**: [GitHub Discussions](https://github.com/fastkit-org/mailbridge/discussions)
- **Changelog**: [CHANGELOG.md](https://github.com/fastkit-org/mailbridge/blob/main/CHANGELOG.md)
