"""
Async tests for SMTP provider.

Tests cover:
- async_send using aiosmtplib
- async_send_bulk reusing a single connection
- Fallback to thread pool when aiosmtplib is unavailable

Run with: pytest tests/test_smtp_async.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from mailbridge.providers.smtp_provider import SMTPProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def smtp_config():
    return {
        'host': 'smtp.example.com',
        'port': 587,
        'username': 'user@example.com',
        'password': 'secret'
    }


@pytest.fixture
def provider(smtp_config):
    return SMTPProvider(**smtp_config)


@pytest.fixture
def simple_message():
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Async SMTP Test',
        body='Hello from async SMTP',
        html=False
    )


def make_mock_smtp_server():
    """Return an async context-manager mock for aiosmtplib.SMTP."""
    server = AsyncMock()
    server.send_message = AsyncMock()
    server.__aenter__ = AsyncMock(return_value=server)
    server.__aexit__ = AsyncMock(return_value=False)
    return server


# =============================================================================
# async_send TESTS
# =============================================================================

class TestSMTPAsyncSend:

    @pytest.mark.asyncio
    async def test_async_send_success(self, provider, simple_message):
        """async_send returns successful EmailResponseDTO."""
        mock_server = make_mock_smtp_server()

        with patch.object(provider, '_get_async_smtp_connection', return_value=mock_server):
            result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.provider == 'smtp'
        mock_server.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_send_correct_recipients(self, provider):
        """async_send passes correct recipient list to send_message."""
        mock_server = make_mock_smtp_server()

        message = EmailMessageDto(
            to=['a@example.com', 'b@example.com'],
            subject='Test',
            body='Body',
            cc=['cc@example.com'],
            bcc=['bcc@example.com']
        )

        with patch.object(provider, '_get_async_smtp_connection', return_value=mock_server):
            await provider.async_send(message)

        call_kwargs = mock_server.send_message.call_args[1]
        recipients = call_kwargs['recipients']
        assert 'a@example.com' in recipients
        assert 'b@example.com' in recipients
        assert 'cc@example.com' in recipients
        assert 'bcc@example.com' in recipients

    @pytest.mark.asyncio
    async def test_async_send_error_raises(self, provider, simple_message):
        """async_send raises EmailSendError when server.send_message fails."""
        mock_server = make_mock_smtp_server()
        mock_server.send_message = AsyncMock(
            side_effect=Exception('Connection reset')
        )

        with patch.object(provider, '_get_async_smtp_connection', return_value=mock_server):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert 'Failed to send email via SMTP' in str(exc_info.value)
        assert exc_info.value.provider == 'smtp'

    @pytest.mark.asyncio
    async def test_async_send_fallback_without_aiosmtplib(self, provider, simple_message):
        """async_send falls back to thread pool when aiosmtplib is unavailable."""
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        with patch('mailbridge.providers.smtp_provider.AIOSMTPLIB_AVAILABLE', False):
            with patch.object(provider, 'send') as mock_send:
                mock_send.return_value = EmailResponseDTO(
                    success=True, message_id=None, provider='smtp'
                )
                result = await provider.async_send(simple_message)

        assert result.success is True
        mock_send.assert_called_once_with(simple_message)


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestSMTPAsyncSendBulk:

    @pytest.mark.asyncio
    async def test_async_send_bulk_reuses_connection(self, provider):
        """async_send_bulk sends all messages over a single SMTP connection."""
        mock_server = make_mock_smtp_server()

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject=f'Test {i}', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch.object(provider, '_get_async_smtp_connection', return_value=mock_server):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 3
        assert result.failed == 0
        # send_message should be called once per message over the same connection
        assert mock_server.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_async_send_bulk_partial_failure(self, provider):
        """async_send_bulk records per-message errors without aborting the whole batch."""
        call_count = 0

        async def send_message_side_effect(msg, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception('Recipient rejected')

        mock_server = make_mock_smtp_server()
        mock_server.send_message = AsyncMock(side_effect=send_message_side_effect)

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Test', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch.object(provider, '_get_async_smtp_connection', return_value=mock_server):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 2
        assert result.failed == 1

        failed = [r for r in result.responses if not r.success]
        assert 'Recipient rejected' in failed[0].error

    @pytest.mark.asyncio
    async def test_async_send_bulk_connection_error_raises(self, provider):
        """async_send_bulk raises EmailSendError when connection itself fails."""
        mock_server = AsyncMock()
        mock_server.__aenter__ = AsyncMock(
            side_effect=Exception('Cannot connect to SMTP server')
        )
        mock_server.__aexit__ = AsyncMock(return_value=False)

        messages = [EmailMessageDto(to='u@example.com', subject='Test', body='Body')]
        bulk = BulkEmailDTO(messages=messages)

        with patch.object(provider, '_get_async_smtp_connection', return_value=mock_server):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send_bulk(bulk)

        assert 'Failed to send bulk emails via SMTP' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_send_bulk_fallback_without_aiosmtplib(self, provider):
        """async_send_bulk falls back to thread pool when aiosmtplib is unavailable."""
        from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
        from mailbridge.dto.email_response_dto import EmailResponseDTO

        messages = [EmailMessageDto(to='u@example.com', subject='Test', body='Body')]
        bulk = BulkEmailDTO(messages=messages)

        with patch('mailbridge.providers.smtp_provider.AIOSMTPLIB_AVAILABLE', False):
            with patch.object(provider, 'send_bulk') as mock_send_bulk:
                mock_send_bulk.return_value = BulkEmailResponseDTO(
                    total=1, successful=1, failed=0,
                    responses=[EmailResponseDTO(success=True, provider='smtp')]
                )
                result = await provider.async_send_bulk(bulk)

        assert result.successful == 1
        mock_send_bulk.assert_called_once_with(bulk)


# =============================================================================
# ASYNC CONTEXT MANAGER
# =============================================================================

class TestSMTPAsyncContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self, smtp_config):
        async with SMTPProvider(**smtp_config) as provider:
            assert isinstance(provider, SMTPProvider)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
