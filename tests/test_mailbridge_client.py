"""
Unit tests for MailBridge client class - FINAL WORKING VERSION

The key insight: We must mock the provider class IN the MailBridge.PROVIDERS dict
BEFORE instantiating MailBridge, not the module-level class.

Run with: pytest tests/test_mailbridge_client.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from mailbridge.client import MailBridge
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.exceptions import ProviderNotFoundError
from mailbridge.providers.base_email_provider import BaseEmailProvider


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_mock_provider_class():
    """
    Create a mock provider CLASS (not instance) that returns a mock provider instance.

    This simulates: SendGridProvider(**config) -> returns mock instance
    """
    mock_instance = Mock(spec=BaseEmailProvider)
    mock_instance.send.return_value = EmailResponseDTO(
        success=True,
        message_id='test-message-id-123',
        provider='mock'
    )
    mock_instance.send_bulk.return_value = BulkEmailResponseDTO.from_responses([
        EmailResponseDTO(success=True, message_id='msg1', provider='mock'),
        EmailResponseDTO(success=True, message_id='msg2', provider='mock'),
    ])
    mock_instance.supports_templates.return_value = True
    mock_instance.supports_bulk_sending.return_value = True
    mock_instance.close.return_value = None

    # Create a mock CLASS that returns the mock instance when called
    mock_class = Mock(return_value=mock_instance)

    return mock_class, mock_instance


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestMailBridgeInitialization:
    """Test MailBridge initialization."""

    def test_initialize_with_sendgrid(self):
        """Test initializing with SendGrid provider."""
        mock_class, mock_instance = create_mock_provider_class()

        # Store original and replace
        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='test-key')

            # Should call mock class with config
            mock_class.assert_called_once_with(api_key='test-key')
            assert mailer.provider_name == 'sendgrid'
            assert mailer.provider == mock_instance
        finally:
            # Restore original
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_initialize_with_mailgun(self):
        """Test initializing with Mailgun provider."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['mailgun']
        MailBridge.PROVIDERS['mailgun'] = mock_class

        try:
            mailer = MailBridge(provider='mailgun', api_key='key', domain='example.com')

            mock_class.assert_called_once_with(api_key='key', domain='example.com')
            assert mailer.provider_name == 'mailgun'
        finally:
            MailBridge.PROVIDERS['mailgun'] = original

    def test_case_insensitive_provider_name(self):
        """Test provider name is case-insensitive."""
        mock_class, _ = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer1 = MailBridge(provider='SendGrid', api_key='key')
            mailer2 = MailBridge(provider='SENDGRID', api_key='key')
            mailer3 = MailBridge(provider='sendgrid', api_key='key')

            assert mailer1.provider_name == 'sendgrid'
            assert mailer2.provider_name == 'sendgrid'
            assert mailer3.provider_name == 'sendgrid'
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_invalid_provider_raises_error(self):
        """Test initializing with invalid provider raises error."""
        with pytest.raises(ProviderNotFoundError) as exc_info:
            MailBridge(provider='invalid_provider', api_key='key')

        assert 'invalid_provider' in str(exc_info.value)
        assert 'Available providers' in str(exc_info.value)

    def test_available_providers(self):
        """Test getting list of available providers."""
        providers = MailBridge.available_providers()

        assert 'sendgrid' in providers
        assert 'mailgun' in providers
        assert 'ses' in providers
        assert 'postmark' in providers
        assert 'brevo' in providers
        assert 'smtp' in providers


# =============================================================================
# SEND METHOD TESTS
# =============================================================================

class TestMailBridgeSend:
    """Test MailBridge send() method."""

    def test_send_simple_email(self):
        """Test sending a simple email."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.send.return_value = EmailResponseDTO(
            success=True,
            message_id='msg-123',
            provider='sendgrid'
        )

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='Test Email',
                body='<h1>Hello</h1>'
            )

            assert response.success is True
            assert response.message_id == 'msg-123'

            mock_instance.send.assert_called_once()

            call_args = mock_instance.send.call_args[0][0]
            assert isinstance(call_args, EmailMessageDto)
            assert call_args.to == ['recipient@example.com']
            assert call_args.subject == 'Test Email'
            assert call_args.body == '<h1>Hello</h1>'
            assert call_args.html is True
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_with_multiple_recipients(self):
        """Test sending to multiple recipients."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to=['user1@example.com', 'user2@example.com'],
                subject='Test',
                body='Body'
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.to == ['user1@example.com', 'user2@example.com']
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_with_cc_bcc(self):
        """Test sending with CC and BCC."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='Test',
                body='Body',
                cc=['cc@example.com'],
                bcc=['bcc@example.com']
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.cc == ['cc@example.com']
            assert call_args.bcc == ['bcc@example.com']
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_with_attachments(self, tmp_path):
        """Test sending with attachments."""
        mock_class, mock_instance = create_mock_provider_class()

        test_file = tmp_path / "document.pdf"
        test_file.write_bytes(b'PDF content')

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='With Attachment',
                body='See attached',
                attachments=[test_file]
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.attachments == [test_file]
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_plain_text(self):
        """Test sending plain text email."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='Plain Text',
                body='Plain text content',
                html=False
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.html is False
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_with_template(self):
        """Test sending template email."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='',
                body='',
                template_id='welcome-template',
                template_data={'name': 'John', 'company': 'Acme'}
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.template_id == 'welcome-template'
            assert call_args.template_data == {'name': 'John', 'company': 'Acme'}
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_with_custom_headers(self):
        """Test sending with custom headers."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='Test',
                body='Body',
                headers={'X-Custom': 'value'}
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.headers == {'X-Custom': 'value'}
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_with_tags(self):
        """Test sending with tags."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            response = mailer.send(
                to='recipient@example.com',
                subject='Test',
                body='Body',
                tags=['campaign', 'november']
            )

            assert response.success is True

            call_args = mock_instance.send.call_args[0][0]
            assert call_args.tags == ['campaign', 'november']
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original


# =============================================================================
# SEND BULK TESTS
# =============================================================================

class TestMailBridgeSendBulk:
    """Test MailBridge send_bulk() method."""

    def test_send_bulk_with_list(self):
        """Test bulk sending with list of messages."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.send_bulk.return_value = BulkEmailResponseDTO.from_responses([
            EmailResponseDTO(success=True, message_id='msg1', provider='sendgrid'),
            EmailResponseDTO(success=True, message_id='msg2', provider='sendgrid'),
        ])

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            messages = [
                EmailMessageDto(to='user1@example.com', subject='Test 1', body='Body 1'),
                EmailMessageDto(to='user2@example.com', subject='Test 2', body='Body 2'),
            ]

            result = mailer.send_bulk(messages)

            assert result.total == 2
            assert result.successful == 2
            assert result.failed == 0

            mock_instance.send_bulk.assert_called_once()

            call_args = mock_instance.send_bulk.call_args[0][0]
            assert isinstance(call_args, BulkEmailDTO)
            assert len(call_args.messages) == 2
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_bulk_with_bulk_dto(self):
        """Test bulk sending with BulkEmailDTO."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.send_bulk.return_value = BulkEmailResponseDTO.from_responses([
            EmailResponseDTO(success=True, message_id='msg1', provider='sendgrid'),
        ])

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            bulk = BulkEmailDTO(
                messages=[
                    EmailMessageDto(to='user@example.com', subject='Test', body='Body')
                ],
                default_from='sender@example.com',
                tags=['bulk']
            )

            result = mailer.send_bulk(bulk)

            assert result.successful == 1
            mock_instance.send_bulk.assert_called_once_with(bulk)
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_bulk_with_default_from(self):
        """Test bulk sending with default_from."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.send_bulk.return_value = BulkEmailResponseDTO.from_responses([
            EmailResponseDTO(success=True, message_id='msg1', provider='sendgrid'),
        ])

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            messages = [
                EmailMessageDto(to='user@example.com', subject='Test', body='Body')
            ]

            result = mailer.send_bulk(messages, default_from='noreply@example.com')

            assert result.successful == 1

            call_args = mock_instance.send_bulk.call_args[0][0]
            assert call_args.default_from == 'noreply@example.com'
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_send_bulk_with_tags(self):
        """Test bulk sending with tags."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.send_bulk.return_value = BulkEmailResponseDTO.from_responses([
            EmailResponseDTO(success=True, message_id='msg1', provider='sendgrid'),
        ])

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            messages = [
                EmailMessageDto(to='user@example.com', subject='Test', body='Body')
            ]

            result = mailer.send_bulk(messages, tags=['campaign', 'november'])

            assert result.successful == 1

            call_args = mock_instance.send_bulk.call_args[0][0]
            assert call_args.tags == ['campaign', 'november']
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original


# =============================================================================
# CAPABILITY TESTS
# =============================================================================

class TestMailBridgeCapabilities:
    """Test capability checking methods."""

    def test_supports_templates(self):
        """Test checking template support."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.supports_templates.return_value = True

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            assert mailer.supports_templates() is True
            mock_instance.supports_templates.assert_called_once()
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_does_not_support_templates(self):
        """Test provider that doesn't support templates."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.supports_templates.return_value = False

        original = MailBridge.PROVIDERS['smtp']
        MailBridge.PROVIDERS['smtp'] = mock_class

        try:
            mailer = MailBridge(
                provider='smtp',
                host='smtp.example.com',
                port=587,
                username='user',
                password='pass'
            )

            assert mailer.supports_templates() is False
        finally:
            MailBridge.PROVIDERS['smtp'] = original

    def test_supports_bulk_sending(self):
        """Test checking bulk sending support."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.supports_bulk_sending.return_value = True

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')

            assert mailer.supports_bulk_sending() is True
            mock_instance.supports_bulk_sending.assert_called_once()
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestMailBridgeContextManager:
    """Test context manager support."""

    def test_context_manager(self):
        """Test using MailBridge as context manager."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            with MailBridge(provider='sendgrid', api_key='key') as mailer:
                assert mailer is not None
                assert isinstance(mailer, MailBridge)

            mock_instance.close.assert_called_once()
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original

    def test_close_method(self):
        """Test explicit close() method."""
        mock_class, mock_instance = create_mock_provider_class()

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            mailer = MailBridge(provider='sendgrid', api_key='key')
            mailer.close()

            mock_instance.close.assert_called_once()
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original


# =============================================================================
# CUSTOM PROVIDER TESTS
# =============================================================================

class TestMailBridgeCustomProvider:
    """Test custom provider registration."""

    def test_register_custom_provider(self):
        """Test registering a custom provider."""
        class CustomProvider(BaseEmailProvider):
            def _validate_config(self):
                pass

            def send(self, message):
                return EmailResponseDTO(success=True, provider='custom')

        MailBridge.register_provider('custom', CustomProvider)

        # Should be able to use custom provider
        mailer = MailBridge(provider='custom', api_key='key')
        assert mailer.provider_name == 'custom'
        assert isinstance(mailer.provider, CustomProvider)

        # Clean up
        del MailBridge.PROVIDERS['custom']

    def test_register_provider_case_insensitive(self):
        """Test provider registration is case-insensitive."""
        class CustomProvider(BaseEmailProvider):
            def _validate_config(self):
                pass

            def send(self, message):
                return EmailResponseDTO(success=True, provider='custom')

        MailBridge.register_provider('MyCustomProvider', CustomProvider)

        # Should be stored as lowercase
        assert 'mycustomprovider' in MailBridge.PROVIDERS

        # Should be able to initialize with any case
        mailer = MailBridge(provider='MYCUSTOMPROVIDER', api_key='key')
        assert mailer.provider_name == 'mycustomprovider'

        # Clean up
        del MailBridge.PROVIDERS['mycustomprovider']

    def test_register_invalid_provider_class(self):
        """Test registering invalid provider class raises error."""
        class InvalidProvider:
            """Does not inherit from BaseEmailProvider."""
            pass

        with pytest.raises(TypeError) as exc_info:
            MailBridge.register_provider('invalid', InvalidProvider)

        assert 'must inherit from BaseEmailProvider' in str(exc_info.value)

    def test_available_providers_includes_custom(self):
        """Test available_providers includes custom providers."""
        class CustomProvider(BaseEmailProvider):
            def _validate_config(self):
                pass

            def send(self, message):
                return EmailResponseDTO(success=True, provider='custom')

        MailBridge.register_provider('mytest', CustomProvider)

        providers = MailBridge.available_providers()
        assert 'mytest' in providers

        # Clean up
        del MailBridge.PROVIDERS['mytest']


# =============================================================================
# INTEGRATION-LIKE TESTS
# =============================================================================

class TestMailBridgeIntegration:
    """Integration-like tests (still using mocks)."""

    def test_full_workflow(self):
        """Test complete workflow: initialize, send, bulk, close."""
        mock_class, mock_instance = create_mock_provider_class()
        mock_instance.send.return_value = EmailResponseDTO(
            success=True,
            message_id='msg-single',
            provider='sendgrid'
        )
        mock_instance.send_bulk.return_value = BulkEmailResponseDTO.from_responses([
            EmailResponseDTO(success=True, message_id='msg-bulk-1', provider='sendgrid'),
            EmailResponseDTO(success=True, message_id='msg-bulk-2', provider='sendgrid'),
        ])
        mock_instance.supports_templates.return_value = True
        mock_instance.supports_bulk_sending.return_value = True

        original = MailBridge.PROVIDERS['sendgrid']
        MailBridge.PROVIDERS['sendgrid'] = mock_class

        try:
            # Initialize
            mailer = MailBridge(provider='sendgrid', api_key='test-key')

            # Check capabilities
            assert mailer.supports_templates() is True
            assert mailer.supports_bulk_sending() is True

            # Send single email
            response = mailer.send(
                to='user@example.com',
                subject='Test',
                body='Body'
            )
            assert response.success is True
            assert response.message_id == 'msg-single'

            # Send bulk
            messages = [
                EmailMessageDto(to='user1@example.com', subject='Bulk 1', body='Body 1'),
                EmailMessageDto(to='user2@example.com', subject='Bulk 2', body='Body 2'),
            ]
            result = mailer.send_bulk(messages)
            assert result.successful == 2

            # Close
            mailer.close()
            mock_instance.close.assert_called_once()
        finally:
            MailBridge.PROVIDERS['sendgrid'] = original


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
