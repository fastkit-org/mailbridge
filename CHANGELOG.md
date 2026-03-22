# Changelog

## [2.1.0] - 2026-03-22

### ✨ Added

#### Async Support
- **`AsyncMailBridge` client**: New async-first client class in `client.py` that mirrors the `MailBridge` API exactly, replacing `send` / `send_bulk` with coroutines
  ```python
  async with AsyncMailBridge(provider='sendgrid', api_key='...') as mailer:
      await mailer.send(to='user@example.com', subject='Hi', body='Hello!')
  ```
- **`async_send` and `async_send_bulk` on all providers**: Every provider now exposes native async methods
  - **SendGrid, Mailgun, Brevo, Postmark**: Native async I/O via `aiohttp` — a single `ClientSession` is reused across all concurrent requests in a bulk send
  - **SMTP**: Native async via `aiosmtplib` — `async_send_bulk` reuses a single SMTP connection for the entire batch
  - **SES**: `boto3` has no async SDK; `async_send` and `async_send_bulk` run boto3 calls concurrently in a thread pool executor to avoid blocking the event loop
  - **Fallback**: All providers fall back to a thread pool executor automatically if the optional async library (`aiohttp` / `aiosmtplib`) is not installed
- **Async context manager** on `BaseEmailProvider` and `AsyncMailBridge`: `async with` is now supported on all providers and both client classes
- **`async_close` on `BaseEmailProvider`**: Mirrors the sync `close` method for proper async teardown
- **`[async]` optional dependency group** in `pyproject.toml`:
  ```bash
  uv sync --extra async   # installs aiohttp + aiosmtplib
  ```
- **Async test suites**: 60+ new tests covering all providers
  - `tests/test_sendgrid_async.py`
  - `tests/test_mailgun_async.py`
  - `tests/test_brevo_async.py`
  - `tests/test_postmark_async.py`
  - `tests/test_smtp_async.py`
  - `tests/test_ses_async.py`
  - `tests/test_async_mailbridge_client.py`

#### Shared Provider Registry
- `MailBridge.PROVIDERS` and `AsyncMailBridge.PROVIDERS` now point to the same module-level `_PROVIDERS` dict — calling `register_provider` on either client immediately makes the new provider available to both

### 🔄 Changed

#### Build tooling: `pip` + `requirements.txt` → `uv`
- **Build backend** switched from `setuptools` to `hatchling` — no more manual `[tool.setuptools] packages` list
- `requirements.txt` and `requirements-dev.txt` are retired; all dependencies are declared in `pyproject.toml` under `[project.optional-dependencies]`
- Added `.python-version` file (`3.11`) so `uv` selects the correct interpreter automatically
- `pytest.ini` reduced to an empty `[pytest]` root marker; all pytest configuration lives in `[tool.pytest.ini_options]` in `pyproject.toml`
- `asyncio_mode = "auto"` added to pytest config — `@pytest.mark.asyncio` decorator is no longer needed on individual async tests

#### Dependency cleanup
- Removed `pydantic` from core `dependencies` — it was listed but never used
- Moved `aiohttp` and `aiosmtplib` from `requirements.txt` to the new `[async]` extra
- `[dev]` extra in `pyproject.toml` is now the single source of truth for the development toolchain, replacing `requirements-dev.txt`; it now correctly includes `pytest-asyncio`, `aiohttp`, `aiosmtplib`, and `requests-mock` which were previously missing

#### Provider improvements (sync)
- `send_bulk` on **Mailgun** and **Postmark** now records per-message failures as `failed` responses in `BulkEmailResponseDTO` instead of raising — consistent with the behavior of all other providers
- `send_bulk` on **SendGrid** and **SES** no longer swallows `EmailSendError` inside the catch-all `except Exception` block
- **Brevo** `send_bulk` and `async_send_bulk` now handle the case where the API returns a single `messageId` string instead of a list
- **Brevo** batch payload logic extracted to `_build_bulk_payload` helper — removes duplication between sync and async paths
- **Mailgun** form-data construction extracted to `_build_aiohttp_form_data` and `_build_form_data` helpers — removes duplication between `async_send` and `_async_send_single`
- **SendGrid** `_build_payload` no longer sets `template_id = message.template_id or {}` (the `or {}` fallback was semantically wrong for a string field)
- Error message in `_send_request` / `_async_send_single` unified to `"SendGrid API error"` across all code paths (was inconsistently `"SendGrid template error"` for non-template sends)
- `BaseEmailProvider` default `async_send` / `async_send_bulk` now use `run_in_executor(None, ...)` (the default thread pool) instead of creating a new `ThreadPoolExecutor` per call, which previously caused executor leaks

### 🧪 Testing
- Total test count increased from 156 to **220+**
- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- Fixed `test_async_send_bulk_partial_failure` in `test_sendgrid_async.py` — `post_side_effect` must be a sync function when used as a `MagicMock` side effect; an `async def` side effect returns a coroutine object instead of the mock response, breaking `__aenter__`

### ⚡ Performance
- Async bulk sends across HTTP providers (SendGrid, Mailgun, Brevo, Postmark) now fire all requests concurrently with `asyncio.gather`, dramatically reducing wall-clock time for large batches
- SMTP bulk sends reuse a single connection for the entire batch (sync and async)
- SES bulk sends run individual boto3 calls concurrently in a thread pool

---

## [2.0.0] - 2025-11-10

### 🎉 Major Release - Complete Rewrite

MailBridge 2.0 is a complete rewrite with significant improvements in architecture, features, and reliability.

### ✨ Added

#### Core Features
- **Template Support**: Dynamic email templates for SendGrid, Amazon SES, Postmark, Mailgun, and Brevo
- **Bulk Sending API**: Native bulk sending with provider-specific optimizations
  - SendGrid: Native batch API (up to 1000 emails per call)
  - Amazon SES: Auto-batching to 50 recipients per API call
  - Postmark: Native batch API (up to 500 emails per call)
  - Mailgun: Native batch API
  - Brevo: Native batch API
- **DTO Classes**: Type-safe data transfer objects for better code quality
  - `EmailMessageDto`: Structured email message
  - `BulkEmailDTO`: Bulk email configuration
  - `EmailResponseDTO`: Unified response format
  - `BulkEmailResponseDTO`: Bulk operation results with success/failure tracking

#### Providers
- **New Provider**: Brevo (formerly Sendinblue) with template and bulk support
- **Enhanced SendGrid**: Native bulk API with personalizations
- **Enhanced SES**: Template support with automatic 50-recipient batching
- **Enhanced Postmark**: Template support with open/click tracking
- **Enhanced Mailgun**: Template support with native bulk API

#### Developer Experience
- **Comprehensive Test Suite**: 156 unit tests with 96% code coverage
- **Complete Examples**: 64 code examples covering all providers and use cases
- **Type Hints**: Full type annotation for better IDE support
- **Error Handling**: Detailed exception classes with meaningful error messages
- **Context Manager Support**: Auto-cleanup with `with` statement

#### Documentation
- Detailed examples for all providers (basic, template, bulk)
- Provider comparison table
- Migration guide from v1.x
- Best practices and production tips

### 🔄 Changed

#### Breaking Changes
- **Provider Initialization**: Now uses keyword arguments for clarity
  ```python
  # v1.x
  mailer = MailBridge('sendgrid', api_key='xxx')
  
  # v2.0
  mailer = MailBridge(provider='sendgrid', api_key='xxx')
  ```

- **Response Format**: Unified response objects across all providers
  ```python
  # v2.0
  response = mailer.send(...)
  print(response.message_id)  # Consistent across all providers
  print(response.success)     # Boolean status
  ```

- **Bulk Sending**: New dedicated bulk API
  ```python
  # v2.0
  from mailbridge import EmailMessageDto
  
  messages = [EmailMessageDto(...), EmailMessageDto(...)]
  result = mailer.send_bulk(messages)
  print(f"Sent: {result.successful}/{result.total}")
  ```

#### Improvements
- **Better Error Messages**: More descriptive errors with actionable information
- **Automatic Batching**: SES automatically batches to respect 50-recipient limit
- **Connection Reuse**: SMTP provider reuses connections for better performance
- **Configuration Validation**: Providers validate configuration on initialization

### 🐛 Fixed
- Fixed SMTP connection handling for large bulk sends
- Fixed attachment encoding issues across all providers
- Fixed template variable serialization for nested data structures
- Fixed error handling for partial bulk send failures

### 📚 Documentation
- Added comprehensive README with quick start guide
- Added 64 code examples covering all features
- Added migration guide from v1.x to v2.0
- Added API reference documentation
- Added provider comparison matrix

### 🧪 Testing
- Added 110 unit tests (96% coverage)
- Provider-specific test suites:
  - SendGrid: 27 tests
  - Amazon SES: 22 tests
  - Postmark: 20 tests
  - SMTP: 15 tests
  - Client: 26 tests
- Automated test pipeline with GitHub Actions (planned)

### 🔒 Security
- Removed hardcoded credentials from examples
- Added environment variable support
- Improved error messages to not leak sensitive data

### ⚡ Performance
- SendGrid: Up to 10x faster bulk sending with native batch API
- SES: Automatic batching reduces API calls by 98% for large sends
- SMTP: Connection pooling for bulk operations
- Reduced memory footprint for large bulk operations

---

## [1.0.0] - 2025-10-25
### Added
- First stable release of **Mailbrig** 🎉
- Unified interface for multiple email providers:
  - **SMTP**
  - **SendGrid**
  - **Mailgun**
  - **Brevo (Sendinblue)**
  - **Amazon SES**
- Centralized API for sending emails with automatic provider selection
- CLI tool (`mailbrig`) for quick provider testing and configuration
- Environment-based configuration via `.env` file or system variables
- Easy extension with custom providers through abstract `ProviderInterface`
- Full test coverage with validation of provider responses
- Comprehensive documentation and usage examples

### Changed
- Project structure migrated to `pyproject.toml` (PEP 621)  
- Published initial version `0.1.0` to [PyPI](https://pypi.org/project/mailbridge) before stable 1.0.0

### Notes
- This marks the **first production-ready stable release**
- Future changes will follow [Semantic Versioning](https://semver.org/)
- Backward compatibility will be maintained across all `1.x.x` versions
