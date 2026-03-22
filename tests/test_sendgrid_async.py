"""
Async tests for SendGrid provider.

Tests cover:
- async_send for simple, template, cc/bcc, error cases
- async_send_bulk for regular, template-batched, and mixed messages
- Fallback to thread pool when aiohttp is unavailable

Run with: pytest tests/test_sendgrid_async.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from mailbridge.providers.sendgrid_provider import SendGridProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sendgrid_config():
    return {
        'api_key': 'SG.test_api_key_12345',
        'from_email': 'sender@example.com'
    }


@pytest.fixture
def provider(sendgrid_config):
    return SendGridProvider(**sendgrid_config)


@pytest.fixture
def simple_message():
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Async Test',
        body='<p>Hello</p>',
        html=True
    )


@pytest.fixture
def template_message():
    return EmailMessageDto(
        to='recipient@example.com',
        template_id='d-async-template',
        template_data={'name': 'Alice'}
    )


def make_mock_response(status=202, headers=None, json_data=None):
    """Build a mock aiohttp response."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.headers = headers or {'X-Message-Id': 'async-msg-id-123'}
    mock_resp.text = AsyncMock(return_value='error body')
    mock_resp.json = AsyncMock(return_value=json_data or {})
    # Make it work as async context manager
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def make_mock_session(response):
    """Build a mock aiohttp.ClientSession."""
    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


# =============================================================================
# async_send TESTS
# =============================================================================

class TestSendGridAsyncSend:

    @pytest.mark.asyncio
    async def test_async_send_simple_email(self, provider, simple_message):
        """async_send returns correct EmailResponseDTO on success."""
        mock_resp = make_mock_response(status=202, headers={'X-Message-Id': 'async-msg-id-123'})
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.message_id == 'async-msg-id-123'
        assert result.provider == 'sendgrid'
        assert result.metadata['status_code'] == 202

    @pytest.mark.asyncio
    async def test_async_send_correct_payload(self, provider, simple_message):
        """async_send sends correct JSON payload to SendGrid."""
        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            await provider.async_send(simple_message)

        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs['json']

        assert payload['personalizations'][0]['to'] == [{'email': 'recipient@example.com'}]
        assert payload['from']['email'] == 'sender@example.com'
        assert payload['subject'] == 'Async Test'
        assert payload['content'][0]['type'] == 'text/html'

    @pytest.mark.asyncio
    async def test_async_send_correct_auth_header(self, provider, simple_message):
        """async_send includes correct Authorization header."""
        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            await provider.async_send(simple_message)

        headers = mock_session.post.call_args[1]['headers']
        assert headers['Authorization'] == 'Bearer SG.test_api_key_12345'

    @pytest.mark.asyncio
    async def test_async_send_template_email(self, provider, template_message):
        """async_send correctly handles template emails."""
        mock_resp = make_mock_response()
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send(template_message)

        assert result.success is True
        payload = mock_session.post.call_args[1]['json']
        assert payload['template_id'] == 'd-async-template'
        assert payload['personalizations'][0]['dynamic_template_data'] == {'name': 'Alice'}
        assert 'subject' not in payload

    @pytest.mark.asyncio
    async def test_async_send_api_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on non-2xx response."""
        mock_resp = make_mock_response(status=400, headers={})
        mock_resp.text = AsyncMock(return_value='Bad Request')
        mock_session = make_mock_session(mock_resp)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert '400' in str(exc_info.value)
        assert exc_info.value.provider == 'sendgrid'

    @pytest.mark.asyncio
    async def test_async_send_network_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError on aiohttp.ClientError."""
        import aiohttp

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(side_effect=aiohttp.ClientConnectionError('Network error'))

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert 'Failed to send email via SendGrid' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_fallback_without_aiohttp(self, provider, simple_message):
        """async_send falls back to thread pool when aiohttp is unavailable."""
        with patch('mailbridge.providers.sendgrid_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send') as mock_send:
                from mailbridge.dto.email_response_dto import EmailResponseDTO
                mock_send.return_value = EmailResponseDTO(
                    success=True, message_id='fallback-id', provider='sendgrid'
                )
                result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.message_id == 'fallback-id'
        mock_send.assert_called_once_with(simple_message)


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestSendGridAsyncSendBulk:

    @pytest.mark.asyncio
    async def test_async_send_bulk_regular_emails(self, provider):
        """async_send_bulk sends each regular email concurrently."""
        mock_resp = make_mock_response(status=202, headers={'X-Message-Id': 'bulk-id'})
        mock_session = make_mock_session(mock_resp)

        messages = [
            EmailMessageDto(to=f'user{i}@example.com', subject=f'Test {i}', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 3
        assert result.failed == 0
        assert mock_session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_async_send_bulk_template_batched(self, provider):
        """async_send_bulk batches template emails with same template_id."""
        mock_resp = make_mock_response(status=202, headers={'X-Message-Id': 'template-bulk-id'})
        mock_session = make_mock_session(mock_resp)

        messages = [
            EmailMessageDto(
                to=f'user{i}@example.com',
                template_id='d-welcome',
                template_data={'name': f'User{i}'}
            )
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        # All 3 template messages should be batched into 1 API call
        assert mock_session.post.call_count == 1
        assert result.total == 1
        assert result.successful == 1

        payload = mock_session.post.call_args[1]['json']
        assert payload['template_id'] == 'd-welcome'
        assert len(payload['personalizations']) == 3

    @pytest.mark.asyncio
    async def test_async_send_bulk_mixed_messages(self, provider):
        """async_send_bulk handles mixed template and regular messages."""
        mock_resp = make_mock_response(status=202, headers={'X-Message-Id': 'mixed-id'})
        mock_session = make_mock_session(mock_resp)

        messages = [
            EmailMessageDto(to='t1@example.com', template_id='d-tmpl', template_data={'x': '1'}),
            EmailMessageDto(to='t2@example.com', template_id='d-tmpl', template_data={'x': '2'}),
            EmailMessageDto(to='r1@example.com', subject='Regular', body='Body'),
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        # 1 batch for template + 1 for regular = 2 API calls
        assert mock_session.post.call_count == 2
        assert result.total == 2
        assert result.successful == 2

    @pytest.mark.asyncio
    async def test_async_send_bulk_partial_failure(self, provider):
        """async_send_bulk records failures without aborting the entire batch."""
        call_count = 0

        # IMPORTANT: post_side_effect must be a sync function, not async.
        # session.post() is called as a regular call that returns an async
        # context manager — if side_effect is async, MagicMock returns a
        # coroutine object instead of the mock response, breaking __aenter__.
        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                resp = make_mock_response(status=500, headers={})
                resp.text = AsyncMock(return_value='Server Error')
                return resp
            return make_mock_response(status=202, headers={'X-Message-Id': f'id-{call_count}'})

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(side_effect=post_side_effect)

        messages = [
            EmailMessageDto(to=f'user{i}@example.com', subject='Test', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 2
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_async_send_bulk_multiple_template_ids(self, provider):
        """async_send_bulk groups template emails by template_id."""
        mock_resp = make_mock_response(status=202, headers={'X-Message-Id': 'multi-tmpl-id'})
        mock_session = make_mock_session(mock_resp)

        messages = [
            EmailMessageDto(to='a@example.com', template_id='d-welcome', template_data={}),
            EmailMessageDto(to='b@example.com', template_id='d-welcome', template_data={}),
            EmailMessageDto(to='c@example.com', template_id='d-newsletter', template_data={}),
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.sendgrid_provider.aiohttp.ClientSession',
                   return_value=mock_session):
            result = await provider.async_send_bulk(bulk)

        # 2 different template_ids → 2 API calls
        assert mock_session.post.call_count == 2
        assert result.total == 2
        assert result.successful == 2

    @pytest.mark.asyncio
    async def test_async_send_bulk_fallback_without_aiohttp(self, provider):
        """async_send_bulk falls back to thread pool when aiohttp is unavailable."""
        from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        messages = [
            EmailMessageDto(to='u@example.com', subject='Test', body='Body')
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.sendgrid_provider.AIOHTTP_AVAILABLE', False):
            with patch.object(provider, 'send_bulk') as mock_send_bulk:
                mock_send_bulk.return_value = BulkEmailResponseDTO(
                    total=1, successful=1, failed=0,
                    responses=[EmailResponseDTO(success=True, provider='sendgrid')]
                )
                result = await provider.async_send_bulk(bulk)

        assert result.successful == 1
        mock_send_bulk.assert_called_once_with(bulk)


# =============================================================================
# ASYNC CONTEXT MANAGER TESTS
# =============================================================================

class TestSendGridAsyncContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self, sendgrid_config):
        """Provider works correctly as async context manager."""
        async with SendGridProvider(**sendgrid_config) as provider:
            assert provider is not None
            assert isinstance(provider, SendGridProvider)


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
