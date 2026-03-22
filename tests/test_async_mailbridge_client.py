"""
Tests for AsyncMailBridge client.

Covers:
- Provider resolution and configuration errors
- async_send delegation to provider.async_send
- async_send_bulk with list and BulkEmailDTO input
- supports_templates / supports_bulk_sending pass-through
- Async context manager (__aenter__ / __aexit__)
- register_provider / available_providers shared registry

Run with: pytest tests/test_async_mailbridge_client.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mailbridge.client import AsyncMailBridge, MailBridge, _PROVIDERS
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.exceptions import ProviderNotFoundError
from mailbridge.providers.base_email_provider import BaseEmailProvider


# =============================================================================
# HELPERS
# =============================================================================

def make_email_response(success=True, message_id='msg-123', provider='sendgrid'):
    return EmailResponseDTO(success=success, message_id=message_id, provider=provider)


def make_bulk_response(total=2, successful=2, failed=0):
    responses = [
        EmailResponseDTO(success=True, message_id=f'msg-{i}', provider='sendgrid')
        for i in range(successful)
    ]
    return BulkEmailResponseDTO(
        total=total, successful=successful, failed=failed, responses=responses
    )


def make_mock_provider(send_return=None, send_bulk_return=None):
    """Return a mock BaseEmailProvider with async_send / async_send_bulk as AsyncMocks."""
    mock = MagicMock(spec=BaseEmailProvider)
    mock.async_send = AsyncMock(return_value=send_return or make_email_response())
    mock.async_send_bulk = AsyncMock(return_value=send_bulk_return or make_bulk_response())
    mock.async_close = AsyncMock()
    mock.supports_templates.return_value = True
    mock.supports_bulk_sending.return_value = True
    return mock


# =============================================================================
# CONFIGURATION / INSTANTIATION TESTS
# =============================================================================

class TestAsyncMailBridgeConfiguration:

    def test_valid_provider_instantiated(self):
        with patch('mailbridge.client._resolve_provider') as mock_resolve:
            mock_resolve.return_value = make_mock_provider()
            client = AsyncMailBridge(provider='sendgrid', api_key='SG.test')

        mock_resolve.assert_called_once_with('sendgrid', {'api_key': 'SG.test'})
        assert client.provider_name == 'sendgrid'

    def test_unknown_provider_raises(self):
        with pytest.raises(ProviderNotFoundError) as exc_info:
            AsyncMailBridge(provider='nonexistent', api_key='x')
        assert 'nonexistent' in str(exc_info.value)

    def test_provider_name_lowercased(self):
        with patch('mailbridge.client._resolve_provider') as mock_resolve:
            mock_resolve.return_value = make_mock_provider()
            client = AsyncMailBridge(provider='SendGrid', api_key='x')
        assert client.provider_name == 'sendgrid'


# =============================================================================
# async_send TESTS
# =============================================================================

class TestAsyncMailBridgeSend:

    @pytest.mark.asyncio
    async def test_send_delegates_to_provider_async_send(self):
        """send() calls provider.async_send with correctly built EmailMessageDto."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        result = await client.send(
            to='user@example.com',
            subject='Hello',
            body='<p>Hi</p>',
        )

        assert result.success is True
        assert result.message_id == 'msg-123'
        mock_provider.async_send.assert_called_once()

        sent_message: EmailMessageDto = mock_provider.async_send.call_args[0][0]
        assert sent_message.to == ['user@example.com']
        assert sent_message.subject == 'Hello'
        assert sent_message.body == '<p>Hi</p>'

    @pytest.mark.asyncio
    async def test_send_passes_all_fields(self):
        """send() forwards every optional field to EmailMessageDto."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        await client.send(
            to=['a@example.com', 'b@example.com'],
            subject='Test',
            body='Body',
            from_email='sender@example.com',
            cc='cc@example.com',
            bcc='bcc@example.com',
            reply_to='reply@example.com',
            html=False,
            headers={'X-Custom': 'yes'},
            template_id='tmpl-1',
            template_data={'key': 'val'},
            tags=['tag1'],
        )

        msg: EmailMessageDto = mock_provider.async_send.call_args[0][0]
        assert msg.to == ['a@example.com', 'b@example.com']
        assert msg.from_email == 'sender@example.com'
        assert msg.cc == ['cc@example.com']
        assert msg.bcc == ['bcc@example.com']
        assert msg.reply_to == 'reply@example.com'
        assert msg.html is False
        assert msg.headers == {'X-Custom': 'yes'}
        assert msg.template_id == 'tmpl-1'
        assert msg.template_data == {'key': 'val'}
        assert msg.tags == ['tag1']

    @pytest.mark.asyncio
    async def test_send_template_email(self):
        """send() with template_id builds a template EmailMessageDto."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        await client.send(
            to='user@example.com',
            template_id='d-welcome',
            template_data={'name': 'Alice'},
        )

        msg: EmailMessageDto = mock_provider.async_send.call_args[0][0]
        assert msg.is_template_email() is True
        assert msg.template_id == 'd-welcome'

    @pytest.mark.asyncio
    async def test_send_propagates_provider_error(self):
        """send() propagates EmailSendError from the provider."""
        from mailbridge.exceptions import EmailSendError

        mock_provider = make_mock_provider()
        mock_provider.async_send = AsyncMock(
            side_effect=EmailSendError('API down', provider='sendgrid')
        )

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        with pytest.raises(EmailSendError) as exc_info:
            await client.send(to='u@example.com', subject='S', body='B')

        assert exc_info.value.provider == 'sendgrid'


# =============================================================================
# async_send_bulk TESTS
# =============================================================================

class TestAsyncMailBridgeSendBulk:

    @pytest.mark.asyncio
    async def test_send_bulk_from_list(self):
        """send_bulk() wraps a list into BulkEmailDTO and calls provider."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject='Hi', body='Body')
            for i in range(2)
        ]

        result = await client.send_bulk(messages)

        assert result.successful == 2
        mock_provider.async_send_bulk.assert_called_once()

        bulk_arg: BulkEmailDTO = mock_provider.async_send_bulk.call_args[0][0]
        assert isinstance(bulk_arg, BulkEmailDTO)
        assert len(bulk_arg.messages) == 2

    @pytest.mark.asyncio
    async def test_send_bulk_from_bulk_dto(self):
        """send_bulk() passes a BulkEmailDTO directly without rewrapping."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        messages = [EmailMessageDto(to='u@example.com', subject='Hi', body='Body')]
        bulk = BulkEmailDTO(messages=messages, default_from='sender@example.com')

        await client.send_bulk(bulk)

        bulk_arg = mock_provider.async_send_bulk.call_args[0][0]
        assert bulk_arg is bulk

    @pytest.mark.asyncio
    async def test_send_bulk_applies_default_from(self):
        """send_bulk() applies default_from to messages that have none."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        messages = [EmailMessageDto(to='u@example.com', subject='Hi', body='Body')]
        await client.send_bulk(messages, default_from='noreply@example.com')

        bulk_arg: BulkEmailDTO = mock_provider.async_send_bulk.call_args[0][0]
        assert bulk_arg.messages[0].from_email == 'noreply@example.com'

    @pytest.mark.asyncio
    async def test_send_bulk_applies_tags(self):
        """send_bulk() propagates tags to the BulkEmailDTO."""
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        messages = [EmailMessageDto(to='u@example.com', subject='Hi', body='Body')]
        await client.send_bulk(messages, tags=['promo', 'q4'])

        bulk_arg: BulkEmailDTO = mock_provider.async_send_bulk.call_args[0][0]
        assert 'promo' in bulk_arg.messages[0].tags
        assert 'q4' in bulk_arg.messages[0].tags


# =============================================================================
# CAPABILITY FLAG TESTS
# =============================================================================

class TestAsyncMailBridgeCapabilities:

    def test_supports_templates_delegates(self):
        mock_provider = make_mock_provider()
        mock_provider.supports_templates.return_value = True

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        assert client.supports_templates() is True
        mock_provider.supports_templates.assert_called_once()

    def test_supports_bulk_sending_delegates(self):
        mock_provider = make_mock_provider()
        mock_provider.supports_bulk_sending.return_value = False

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='smtp', host='localhost',
                                     port=25, username='u', password='p')

        assert client.supports_bulk_sending() is False


# =============================================================================
# ASYNC CONTEXT MANAGER TESTS
# =============================================================================

class TestAsyncMailBridgeContextManager:

    @pytest.mark.asyncio
    async def test_aenter_returns_client(self):
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        async with client as c:
            assert c is client

    @pytest.mark.asyncio
    async def test_aexit_calls_async_close(self):
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            async with AsyncMailBridge(provider='sendgrid', api_key='x'):
                pass

        mock_provider.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_close_calls_async_close(self):
        mock_provider = make_mock_provider()

        with patch('mailbridge.client._resolve_provider', return_value=mock_provider):
            client = AsyncMailBridge(provider='sendgrid', api_key='x')

        await client.close()
        mock_provider.async_close.assert_called_once()


# =============================================================================
# SHARED REGISTRY TESTS
# =============================================================================

class TestSharedProviderRegistry:

    def test_available_providers_match_mailbridge(self):
        assert AsyncMailBridge.available_providers() == MailBridge.available_providers()

    def test_register_provider_visible_to_both_clients(self):
        class DummyProvider(BaseEmailProvider):
            def _validate_config(self): pass
            def send(self, message): pass
            def send_bulk(self, bulk): pass

        original_providers = set(_PROVIDERS.keys())

        try:
            MailBridge.register_provider('dummy_shared', DummyProvider)
            assert 'dummy_shared' in AsyncMailBridge.available_providers()
            assert 'dummy_shared' in MailBridge.available_providers()
        finally:
            _PROVIDERS.pop('dummy_shared', None)

    def test_register_provider_async_client(self):
        class AnotherDummy(BaseEmailProvider):
            def _validate_config(self): pass
            def send(self, message): pass
            def send_bulk(self, bulk): pass

        try:
            AsyncMailBridge.register_provider('async_dummy', AnotherDummy)
            assert 'async_dummy' in MailBridge.available_providers()
            assert 'async_dummy' in AsyncMailBridge.available_providers()
        finally:
            _PROVIDERS.pop('async_dummy', None)

    def test_register_non_provider_raises(self):
        with pytest.raises(TypeError):
            MailBridge.register_provider('bad', object)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
