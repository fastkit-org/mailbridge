"""
Async tests for Mailgun provider.

Tests cover:
- async_send for simple, template, attachment, error cases
- async_send_bulk with concurrent sending and partial failure handling
- Fallback to thread pool when aiohttp is unavailable

Run with: pytest tests/test_mailgun_async.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mailbridge.providers.mailgun_provider import MailgunProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mailgun_config():
    return {
        'api_key': 'test-mailgun-key',
        'endpoint': 'https://api.mailgun.net/v3/example.com',
        'from_email': 'sender@example.com'
    }


@pytest.fixture
def provider(mailgun_config):
    return MailgunProvider(**mailgun_config)


@pytest.fixture
def simple_message():
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Async Mailgun Test',
        body='<p>Hello from Mailgun</p>',
        html=True
    )


def make_mock_response(status=200, json_data=None):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.text = AsyncMock(return_value='error')
    mock_resp.json = AsyncMock(return_value=json_data or {'id': 'mg-async-id', 'message': 'Queued'})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def make_mock_session(response):
    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


# =============================================================================
# async_send TESTS
# =============================================================================

class TestMailgunAsyncSend:

    @pytest.mark.asyncio
    async def test_async_send_success(self, provider, simple_message):
        """async_send returns correct EmailResponseDTO on success."""
        mock_resp = make_mock_response(json_data={'id': 'mg-id-123', 'message': 'Queued'})
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.message_id == 'mg-id-123'
        assert result.provider == 'mailgun'
        assert result.metadata['message'] == 'Queued'

    @pytest.mark.asyncio
    async def test_async_send_uses_basic_auth(self, provider, simple_message):
        """async_send authenticates with BasicAuth."""
        import aiohttp as real_aiohttp

        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with patch('mailbridge.providers.mailgun_provider.aiohttp.BasicAuth',
                       wraps=real_aiohttp.BasicAuth) as mock_auth:
                await provider.async_send(simple_message)

        mock_auth.assert_called_once_with('api', 'test-mailgun-key')

    @pytest.mark.asyncio
    async def test_async_send_template_email(self, provider):
        """async_send correctly handles template emails."""
        mock_resp = make_mock_response(json_data={'id': 'tmpl-id', 'message': 'Queued'})
        mock_session = make_mock_session(mock_resp)

        message = EmailMessageDto(
            to='user@example.com',
            template_id='welcome-template',
            template_data={'first_name': 'Alice'}
        )

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(message)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_async_send_api_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on non-200 response."""
        mock_resp = make_mock_response(status=401)
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert '401' in str(exc_info.value)
        assert exc_info.value.provider == 'mailgun'

    @pytest.mark.asyncio
    async def test_async_send_network_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on aiohttp.ClientError."""
        import aiohttp

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(side_effect=aiohttp.ClientConnectionError('timeout'))

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert 'Failed to send email via Mailgun' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_fallback_without_aiohttp(self, provider, simple_message):
        """async_send falls back to thread pool when aiohttp is unavailable."""
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        with patch('mailbridge.providers.mailgun_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send') as mock_send:
                mock_send.return_value = EmailResponseDTO(
                    success=True, message_id='fallback', provider='mailgun'
                )
                result = await provider.async_send(simple_message)

        assert result.success is True
        mock_send.assert_called_once_with(simple_message)


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestMailgunAsyncSendBulk:

    @pytest.mark.asyncio
    async def test_async_send_bulk_success(self, provider):
        """async_send_bulk sends all messages concurrently."""
        call_count = 0

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return make_mock_response(json_data={'id': f'mg-{call_count}', 'message': 'Queued'})

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=post_side_effect)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        messages = [
            EmailMessageDto(to=f'user{i}@example.com', subject=f'Test {i}', body='Body')
            for i in range(4)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 4
        assert result.successful == 4
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_async_send_bulk_partial_failure(self, provider):
        """async_send_bulk records per-message failures without stopping the batch."""
        call_count = 0

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                resp = make_mock_response(status=500)
                resp.text = AsyncMock(return_value='Internal Server Error')
                return resp
            return make_mock_response(json_data={'id': f'ok-{call_count}', 'message': 'Queued'})

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=post_side_effect)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Test', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.mailgun_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 2
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_async_send_bulk_fallback_without_aiohttp(self, provider):
        """async_send_bulk falls back to thread pool when aiohttp is unavailable."""
        from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        messages = [EmailMessageDto(to='u@example.com', subject='Test', body='Body')]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.mailgun_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send_bulk') as mock_send_bulk:
                mock_send_bulk.return_value = BulkEmailResponseDTO(
                    total=1, successful=1, failed=0,
                    responses=[EmailResponseDTO(success=True, provider='mailgun')]
                )
                result = await provider.async_send_bulk(bulk)

        assert result.successful == 1
        mock_send_bulk.assert_called_once_with(bulk)


# =============================================================================
# ASYNC CONTEXT MANAGER
# =============================================================================

class TestMailgunAsyncContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mailgun_config):
        async with MailgunProvider(**mailgun_config) as provider:
            assert isinstance(provider, MailgunProvider)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
