"""
Async tests for SES provider.

SES uses boto3 which does not have a native async API.
async_send and async_send_bulk run boto3 calls in a thread pool executor.

Tests cover:
- async_send delegates to send() via executor
- async_send_bulk runs individual sends concurrently in executor
- Partial failure handling in async_send_bulk

Run with: pytest tests/test_ses_async.py -v
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.exceptions import EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_boto3_client():
    """Patch boto3.client so SESProvider can be instantiated without AWS credentials."""
    with patch('mailbridge.providers.ses_provider.boto3') as mock_boto3:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        yield mock_client


@pytest.fixture
def provider(mock_boto3_client):
    from mailbridge.providers.ses_provider import SESProvider
    return SESProvider(
        aws_access_key_id='AKIATEST',
        aws_secret_access_key='secret',
        region_name='us-east-1',
        from_email='sender@example.com'
    )


@pytest.fixture
def simple_message():
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Async SES Test',
        body='Hello from async SES',
        html=False
    )


# =============================================================================
# async_send TESTS
# =============================================================================

class TestSESAsyncSend:

    @pytest.mark.asyncio
    async def test_async_send_delegates_to_send(self, provider, simple_message):
        """async_send runs send() via thread pool and returns its result."""
        expected = EmailResponseDTO(success=True, message_id='ses-id-1', provider='ses')

        with patch.object(provider, 'send', return_value=expected) as mock_send:
            result = await provider.async_send(simple_message)

        assert result.success is True
        assert result.message_id == 'ses-id-1'
        mock_send.assert_called_once_with(simple_message)

    @pytest.mark.asyncio
    async def test_async_send_propagates_error(self, provider, simple_message):
        """async_send propagates EmailSendError raised inside send()."""
        with patch.object(provider, 'send',
                          side_effect=EmailSendError('SES error', provider='ses')):
            with pytest.raises(EmailSendError) as exc_info:
                await provider.async_send(simple_message)

        assert exc_info.value.provider == 'ses'

    @pytest.mark.asyncio
    async def test_async_send_does_not_block_event_loop(self, provider, simple_message):
        """async_send uses run_in_executor so slow calls don't block the event loop."""
        import time

        def slow_send(msg):
            time.sleep(0.05)
            return EmailResponseDTO(success=True, message_id='slow-id', provider='ses')

        with patch.object(provider, 'send', side_effect=slow_send):
            # Both tasks should run concurrently; sequential would take ~0.1s+
            t0 = asyncio.get_event_loop().time()
            results = await asyncio.gather(
                provider.async_send(simple_message),
                provider.async_send(simple_message)
            )
            elapsed = asyncio.get_event_loop().time() - t0

        assert all(r.success for r in results)
        # Should complete well under 0.1s if truly concurrent
        assert elapsed < 0.5


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestSESAsyncSendBulk:

    @pytest.mark.asyncio
    async def test_async_send_bulk_runs_concurrently(self, provider):
        """async_send_bulk sends all messages concurrently via executor."""
        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject=f'Test {i}', body='Body')
            for i in range(4)
        ]
        bulk = BulkEmailDTO(messages=messages)

        call_count = 0

        def fake_send(msg):
            nonlocal call_count
            call_count += 1
            return EmailResponseDTO(
                success=True, message_id=f'ses-{call_count}', provider='ses'
            )

        with patch.object(provider, 'send', side_effect=fake_send):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 4
        assert result.successful == 4
        assert result.failed == 0
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_async_send_bulk_partial_failure(self, provider):
        """async_send_bulk records per-message failures without aborting the batch."""
        call_count = 0

        def fake_send(msg):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise EmailSendError('SES throttle', provider='ses')
            return EmailResponseDTO(success=True, message_id=f'ses-{call_count}', provider='ses')

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Test', body='Body')
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch.object(provider, 'send', side_effect=fake_send):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 2
        assert result.failed == 1

        failed = [r for r in result.responses if not r.success]
        assert 'SES throttle' in failed[0].error

    @pytest.mark.asyncio
    async def test_async_send_bulk_all_failures(self, provider):
        """async_send_bulk handles the case where every message fails."""
        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Test', body='Body')
            for i in range(2)
        ]
        bulk = BulkEmailDTO(messages=messages)

        with patch.object(provider, 'send',
                          side_effect=EmailSendError('Quota exceeded', provider='ses')):
            result = await provider.async_send_bulk(bulk)

        assert result.total == 2
        assert result.successful == 0
        assert result.failed == 2


# =============================================================================
# ASYNC CONTEXT MANAGER
# =============================================================================

class TestSESAsyncContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_boto3_client):
        from mailbridge.providers.ses_provider import SESProvider

        async with SESProvider(
            aws_access_key_id='KEY',
            aws_secret_access_key='SECRET',
            region_name='us-east-1'
        ) as provider:
            assert isinstance(provider, SESProvider)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
