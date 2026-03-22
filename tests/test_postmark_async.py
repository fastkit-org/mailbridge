"""
Async tests for Postmark provider.

Tests cover:
- async_send for simple, template, error cases
- async_send_bulk with concurrent sending and partial failure handling
- Fallback to thread pool when aiohttp is unavailable

Run with: pytest tests/test_postmark_async.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mailbridge.providers.postmark_provider import PostmarkProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def postmark_config():
    return {
        'server_token': 'test-postmark-token',
        'from_email': 'sender@example.com'
    }


@pytest.fixture
def provider(postmark_config):
    return PostmarkProvider(**postmark_config)


@pytest.fixture
def simple_message():
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Async Postmark Test',
        body='<p>Hello from Postmark</p>',
        html=True
    )


def make_mock_response(status=200, json_data=None):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {
        'MessageID': 'pm-async-id',
        'SubmittedAt': '2024-01-01T00:00:00Z',
        'To': 'recipient@example.com'
    })
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

class TestPostmarkAsyncSend:

    @pytest.mark.asyncio
    async def test_async_send_success(self, provider, simple_message):
        """async_send returns correct EmailResponseDTO on success."""
        mock_resp = make_mock_response(json_data={
            'MessageID': 'pm-id-abc',
            'SubmittedAt': '2024-01-01T00:00:00Z',
            'To': 'recipient@example.com'
        })
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.message_id == 'pm-id-abc'
        assert result.provider == 'postmark'
        assert result.metadata['submitted_at'] == '2024-01-01T00:00:00Z'

    @pytest.mark.asyncio
    async def test_async_send_correct_server_token_header(self, provider, simple_message):
        """async_send sends correct X-Postmark-Server-Token header."""
        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            await provider.async_send(simple_message)

        headers = mock_session.post.call_args[1]['headers']
        assert headers['X-Postmark-Server-Token'] == 'test-postmark-token'

    @pytest.mark.asyncio
    async def test_async_send_template_email(self, provider):
        """async_send handles template emails correctly."""
        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        message = EmailMessageDto(
            to='user@example.com',
            template_id='welcome-tpl',
            template_data={'name': 'Charlie'}
        )

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(message)

        assert result.success is True
        payload = mock_session.post.call_args[1]['json']
        assert payload['TemplateId'] == 'welcome-tpl'
        assert payload['TemplateModel'] == {'name': 'Charlie'}

    @pytest.mark.asyncio
    async def test_async_send_api_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on non-200 response."""
        mock_resp = make_mock_response(
            status=422,
            json_data={'ErrorCode': 300, 'Message': 'Invalid email address'}
        )
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert exc_info.value.provider == 'postmark'
        assert '300' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_network_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on aiohttp.ClientError."""
        import aiohttp

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            side_effect=aiohttp.ClientConnectionError('Connection refused')
        )

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert 'Failed to send email via Postmark' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_fallback_without_aiohttp(self, provider, simple_message):
        """async_send falls back to thread pool when aiohttp is unavailable."""
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        with patch('mailbridge.providers.postmark_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send') as mock_send:
                mock_send.return_value = EmailResponseDTO(
                    success=True, message_id='fallback', provider='postmark'
                )
                result = await provider.async_send(simple_message)

        assert result.success is True
        mock_send.assert_called_once_with(simple_message)


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestPostmarkAsyncSendBulk:

    @pytest.mark.asyncio
    async def test_async_send_bulk_success(self, provider):
        """async_send_bulk sends all messages concurrently."""
        call_count = 0

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return make_mock_response(json_data={
                'MessageID': f'pm-{call_count}',
                'SubmittedAt': '2024-01-01T00:00:00Z',
                'To': f'user{call_count}@example.com'
            })

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=post_side_effect)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        messages = [
            EmailMessageDto(to=f'user{i}@example.com', subject=f'Test {i}', body='Body')
            for i in range(4)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 4
        assert result.successful == 4
        assert result.failed == 0
        assert mock_session.post.call_count == 4

    @pytest.mark.asyncio
    async def test_async_send_bulk_partial_failure(self, provider):
        """async_send_bulk records failures per-message without stopping others."""
        call_count = 0

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return make_mock_response(
                    status=422,
                    json_data={'ErrorCode': 300, 'Message': 'Invalid address'}
                )
            return make_mock_response(json_data={
                'MessageID': f'pm-{call_count}',
                'SubmittedAt': '2024-01-01T00:00:00Z',
                'To': 'ok@example.com'
            })

        mock_session = AsyncMock()
        mock_session.post = MagicMock(side_effect=post_side_effect)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Test', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.postmark_provider.aiohttp.ClientSession',
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

        with patch('mailbridge.providers.postmark_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send_bulk') as mock_send_bulk:
                mock_send_bulk.return_value = BulkEmailResponseDTO(
                    total=1, successful=1, failed=0,
                    responses=[EmailResponseDTO(success=True, provider='postmark')]
                )
                result = await provider.async_send_bulk(bulk)

        assert result.successful == 1
        mock_send_bulk.assert_called_once_with(bulk)


# =============================================================================
# ASYNC CONTEXT MANAGER
# =============================================================================

class TestPostmarkAsyncContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self, postmark_config):
        async with PostmarkProvider(**postmark_config) as provider:
            assert isinstance(provider, PostmarkProvider)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
