"""
Async tests for Brevo provider.

Tests cover:
- async_send for simple, template, error cases
- async_send_bulk using Brevo's batch (messageVersions) endpoint
- Fallback to thread pool when aiohttp is unavailable

Run with: pytest tests/test_brevo_async.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mailbridge.providers.brevo_provider import BrevoProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def brevo_config():
    return {
        'api_key': 'xkeysib-test-key',
        'from_email': 'sender@example.com'
    }


@pytest.fixture
def provider(brevo_config):
    return BrevoProvider(**brevo_config)


@pytest.fixture
def simple_message():
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Async Brevo Test',
        body='<p>Hello from Brevo</p>',
        html=True
    )


def make_mock_response(status=201, json_data=None):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {'messageId': 'brevo-async-id'})
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

class TestBrevoAsyncSend:

    @pytest.mark.asyncio
    async def test_async_send_success(self, provider, simple_message):
        """async_send returns correct EmailResponseDTO on success."""
        mock_resp = make_mock_response(json_data={'messageId': 'brevo-id-123'})
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.message_id == 'brevo-id-123'
        assert result.provider == 'brevo'

    @pytest.mark.asyncio
    async def test_async_send_correct_auth_header(self, provider, simple_message):
        """async_send sends api-key header."""
        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            await provider.async_send(simple_message)

        headers = mock_session.post.call_args[1]['headers']
        assert headers['api-key'] == 'xkeysib-test-key'

    @pytest.mark.asyncio
    async def test_async_send_template_email(self, provider):
        """async_send handles template emails correctly."""
        mock_resp = make_mock_response(json_data={'messageId': 'tmpl-id'})
        mock_session = make_mock_session(mock_resp)

        message = EmailMessageDto(
            to='user@example.com',
            template_id=42,
            template_data={'first_name': 'Bob'}
        )

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(message)

        assert result.success is True
        payload = mock_session.post.call_args[1]['json']
        assert payload['templateId'] == 42
        assert payload['params'] == {'first_name': 'Bob'}

    @pytest.mark.asyncio
    async def test_async_send_api_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on non-2xx response."""
        mock_resp = make_mock_response(
            status=400,
            json_data={'code': 'invalid_parameter', 'message': 'Bad email'}
        )
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert exc_info.value.provider == 'brevo'
        assert 'invalid_parameter' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_network_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on aiohttp.ClientError."""
        import aiohttp

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(side_effect=aiohttp.ClientConnectionError('timeout'))

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert 'Failed to send email via Brevo' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_fallback_without_aiohttp(self, provider, simple_message):
        """async_send falls back to thread pool when aiohttp is unavailable."""
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        with patch('mailbridge.providers.brevo_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send') as mock_send:
                mock_send.return_value = EmailResponseDTO(
                    success=True, message_id='fallback', provider='brevo'
                )
                result = await provider.async_send(simple_message)

        assert result.success is True
        mock_send.assert_called_once_with(simple_message)


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestBrevoAsyncSendBulk:

    @pytest.mark.asyncio
    async def test_async_send_bulk_uses_batch_endpoint(self, provider):
        """async_send_bulk sends a single batch request via messageVersions."""
        mock_resp = make_mock_response(
            json_data={'messageId': ['id-1', 'id-2', 'id-3']}
        )
        mock_session = make_mock_session(mock_resp)

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Newsletter', body='Hello')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages, default_from='batch@example.com')

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        # Should be exactly 1 API call (batch)
        assert mock_session.post.call_count == 1
        assert result.total == 3
        assert result.successful == 3

        payload = mock_session.post.call_args[1]['json']
        assert 'messageVersions' in payload
        assert len(payload['messageVersions']) == 3

    @pytest.mark.asyncio
    async def test_async_send_bulk_sender_from_default(self, provider):
        """async_send_bulk uses default_from as sender."""
        mock_resp = make_mock_response(json_data={'messageId': ['id-1']})
        mock_session = make_mock_session(mock_resp)

        messages = [EmailMessageDto(to='u@example.com', subject='Test', body='Body')]
        bulk = BulkEmailDTO(messages=messages, default_from='noreply@example.com')

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            await provider.async_send_bulk(bulk)

        payload = mock_session.post.call_args[1]['json']
        assert payload['sender']['email'] == 'noreply@example.com'

    @pytest.mark.asyncio
    async def test_async_send_bulk_api_error_raises(self, provider):
        """async_send_bulk raises EmailSendError on API failure."""
        mock_resp = make_mock_response(
            status=500,
            json_data={'code': 'server_error', 'message': 'Internal error'}
        )
        mock_session = make_mock_session(mock_resp)

        messages = [EmailMessageDto(to='u@example.com', subject='Test', body='Body')]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.brevo_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send_bulk(bulk)

        assert exc_info.value.provider == 'brevo'

    @pytest.mark.asyncio
    async def test_async_send_bulk_fallback_without_aiohttp(self, provider):
        """async_send_bulk falls back to thread pool when aiohttp is unavailable."""
        from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        messages = [EmailMessageDto(to='u@example.com', subject='Test', body='Body')]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.brevo_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send_bulk') as mock_send_bulk:
                mock_send_bulk.return_value = BulkEmailResponseDTO(
                    total=1, successful=1, failed=0,
                    responses=[EmailResponseDTO(success=True, provider='brevo')]
                )
                result = await provider.async_send_bulk(bulk)

        assert result.successful == 1
        mock_send_bulk.assert_called_once_with(bulk)


# =============================================================================
# ASYNC CONTEXT MANAGER
# =============================================================================

class TestBrevoAsyncContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self, brevo_config):
        async with BrevoProvider(**brevo_config) as provider:
            assert isinstance(provider, BrevoProvider)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
