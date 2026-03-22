"""
Unit tests for SendGrid provider.

Tests cover:
- Configuration validation
- Regular email sending
- Template email sending
- Bulk email sending
- Error handling
- Attachments
- CC/BCC/Reply-To

Run with: pytest tests/test_sendgrid_provider.py -v
"""

import pytest
from unittest.mock import Mock, patch
import base64

from mailbridge.providers.sendgrid_provider import SendGridProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import ConfigurationError, EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sendgrid_config():
    """SendGrid configuration fixture."""
    return {
        'api_key': 'SG.test_api_key_12345',
        'from_email': 'sender@example.com'
    }


@pytest.fixture
def sendgrid_provider(sendgrid_config):
    """SendGrid provider fixture."""
    return SendGridProvider(**sendgrid_config)


@pytest.fixture
def simple_message():
    """Simple email message fixture."""
    return EmailMessageDto(
        to='recipient@example.com',
        subject='Test Email',
        body='<h1>Hello World</h1>',
        html=True
    )


@pytest.fixture
def template_message():
    """Template email message fixture."""
    return EmailMessageDto(
        to='recipient@example.com',
        template_id='d-1234567890abcdef',
        template_data={
            'name': 'John Doe',
            'company': 'Acme Corp'
        }
    )


@pytest.fixture
def mock_requests_response():
    """Mock requests response fixture."""
    mock_response = Mock()
    mock_response.status_code = 202
    mock_response.headers = {'X-Message-Id': 'test_message_id_123'}
    return mock_response


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestSendGridConfiguration:
    """Test SendGrid provider configuration."""

    def test_valid_configuration(self, sendgrid_config):
        """Test provider initializes with valid config."""
        provider = SendGridProvider(**sendgrid_config)

        assert provider.config['api_key'] == 'SG.test_api_key_12345'
        assert provider.config['from_email'] == 'sender@example.com'
        assert provider.endpoint == 'https://api.sendgrid.com/v3/mail/send'

    def test_custom_endpoint(self, sendgrid_config):
        """Test provider accepts custom endpoint."""
        sendgrid_config['endpoint'] = 'https://custom.sendgrid.com/v3/mail/send'
        provider = SendGridProvider(**sendgrid_config)

        assert provider.endpoint == 'https://custom.sendgrid.com/v3/mail/send'

    def test_missing_api_key(self):
        """Test provider raises error when api_key is missing."""
        with pytest.raises(ConfigurationError) as exc_info:
            SendGridProvider(from_email='sender@example.com')

        assert 'api_key' in str(exc_info.value)

    def test_supports_templates(self, sendgrid_provider):
        """Test provider indicates template support."""
        assert sendgrid_provider.supports_templates() is True

    def test_supports_bulk_sending(self, sendgrid_provider):
        """Test provider indicates bulk sending support."""
        assert sendgrid_provider.supports_bulk_sending() is True


# =============================================================================
# REGULAR EMAIL TESTS
# =============================================================================

class TestSendGridRegularEmail:
    """Test regular email sending."""

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_simple_email(self, mock_post, sendgrid_provider, simple_message, mock_requests_response):
        """Test sending a simple email."""
        mock_post.return_value = mock_requests_response

        response = sendgrid_provider.send(simple_message)

        # Check response
        assert response.success is True
        assert response.message_id == 'test_message_id_123'
        assert response.provider == 'sendgrid'
        assert response.metadata['status_code'] == 202

        # Check API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args

        # Check endpoint
        assert call_args[0][0] == 'https://api.sendgrid.com/v3/mail/send'

        # Check headers
        headers = call_args[1]['headers']
        assert 'Bearer SG.test_api_key_12345' in headers['Authorization']
        assert headers['Content-Type'] == 'application/json'

        # Check payload
        payload = call_args[1]['json']
        assert payload['personalizations'][0]['to'] == [{'email': 'recipient@example.com'}]
        assert payload['from']['email'] == 'sender@example.com'
        assert payload['subject'] == 'Test Email'
        assert payload['content'][0]['type'] == 'text/html'
        assert payload['content'][0]['value'] == '<h1>Hello World</h1>'

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_with_cc_bcc(self, mock_post, sendgrid_provider, mock_requests_response):
        """Test sending email with CC and BCC."""
        mock_post.return_value = mock_requests_response

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Test body',
            cc=['cc1@example.com', 'cc2@example.com'],
            bcc=['bcc@example.com']
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        # Check payload
        payload = mock_post.call_args[1]['json']
        assert payload['personalizations'][0]['cc'] == [
            {'email': 'cc1@example.com'},
            {'email': 'cc2@example.com'}
        ]
        assert payload['personalizations'][0]['bcc'] == [
            {'email': 'bcc@example.com'}
        ]

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_with_reply_to(self, mock_post, sendgrid_provider, mock_requests_response):
        """Test sending email with Reply-To header."""
        mock_post.return_value = mock_requests_response

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Test body',
            reply_to='reply@example.com'
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        payload = mock_post.call_args[1]['json']
        assert payload['reply_to']['email'] == 'reply@example.com'

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_with_custom_headers(self, mock_post, sendgrid_provider, mock_requests_response):
        """Test sending email with custom headers."""
        mock_post.return_value = mock_requests_response

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Test body',
            headers={'X-Custom-Header': 'custom-value', 'X-Priority': '1'}
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        payload = mock_post.call_args[1]['json']
        assert payload['headers']['X-Custom-Header'] == 'custom-value'
        assert payload['headers']['X-Priority'] == '1'

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_plain_text(self, mock_post, sendgrid_provider, mock_requests_response):
        """Test sending plain text email."""
        mock_post.return_value = mock_requests_response

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Plain text body',
            html=False
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        payload = mock_post.call_args[1]['json']
        assert payload['content'][0]['type'] == 'text/plain'
        assert payload['content'][0]['value'] == 'Plain text body'

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_with_attachments(self, mock_post, sendgrid_provider, mock_requests_response, tmp_path):
        """Test sending email with attachments."""
        mock_post.return_value = mock_requests_response

        # Create temporary file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Test body',
            attachments=[test_file]
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        payload = mock_post.call_args[1]['json']
        assert 'attachments' in payload
        assert len(payload['attachments']) == 1
        assert payload['attachments'][0]['filename'] == 'test.txt'
        assert payload['attachments'][0]['type'] == 'application/octet-stream'

        # Check base64 encoding
        content = base64.b64decode(payload['attachments'][0]['content'])
        assert content.decode() == 'Test content'

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_with_tuple_attachment(self, mock_post, sendgrid_provider, mock_requests_response):
        """Test sending email with tuple attachment."""
        mock_post.return_value = mock_requests_response

        attachment = ('report.pdf', b'PDF content', 'application/pdf')

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Test body',
            attachments=[attachment]
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        payload = mock_post.call_args[1]['json']
        assert payload['attachments'][0]['filename'] == 'report.pdf'
        assert payload['attachments'][0]['type'] == 'application/pdf'

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_api_error(self, mock_post, sendgrid_provider, simple_message):
        """Test handling of SendGrid API error."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = 'Bad Request: Invalid email'
        mock_post.return_value = mock_response

        with pytest.raises(EmailSendError) as exc_info:
            sendgrid_provider.send(simple_message)
        assert 'SendGrid API error' in str(exc_info.value)
        assert '400' in str(exc_info.value)

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_network_error(self, mock_post, sendgrid_provider, simple_message):
        """Test handling of network error."""
        import requests
        mock_post.side_effect = requests.ConnectionError('Network error')

        with pytest.raises(EmailSendError) as exc_info:
            sendgrid_provider.send(simple_message)

        assert 'Failed to send email via SendGrid' in str(exc_info.value)


# =============================================================================
# TEMPLATE EMAIL TESTS
# =============================================================================

class TestSendGridTemplateEmail:
    """Test template email sending."""

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_template_email(self, mock_post, sendgrid_provider, template_message, mock_requests_response):
        """Test sending a template email."""
        mock_post.return_value = mock_requests_response

        response = sendgrid_provider.send(template_message)

        assert response.success is True
        assert response.message_id == 'test_message_id_123'

        # Check payload
        payload = mock_post.call_args[1]['json']
        assert payload['template_id'] == 'd-1234567890abcdef'
        assert payload['personalizations'][0]['dynamic_template_data'] == {
            'name': 'John Doe',
            'company': 'Acme Corp'
        }

        # Should NOT have subject or content
        assert 'subject' not in payload
        assert 'content' not in payload

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_template_with_empty_data(self, mock_post, sendgrid_provider, mock_requests_response):
        """Test template email with no template data — None is normalized to {}."""
        mock_post.return_value = mock_requests_response

        message = EmailMessageDto(
            to='recipient@example.com',
            template_id='d-template-id',
            template_data=None,
        )

        response = sendgrid_provider.send(message)

        assert response.success is True

        # template_data=None is normalized to {} so SendGrid never receives null
        payload = mock_post.call_args[1]['json']
        assert payload['personalizations'][0]['dynamic_template_data'] == {}

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_template_is_detected(self, mock_post, sendgrid_provider, template_message):
        """Test that template emails are properly detected."""
        mock_post.return_value = Mock(status_code=202, headers={'X-Message-Id': 'test_id'})

        assert template_message.is_template_email() is True

        sendgrid_provider.send(template_message)

        payload = mock_post.call_args[1]['json']
        assert 'template_id' in payload


# =============================================================================
# BULK EMAIL TESTS
# =============================================================================

class TestSendGridBulkEmail:
    """Test bulk email sending."""

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_bulk_regular_emails(self, mock_post, sendgrid_provider):
        """Test sending bulk regular emails."""
        mock_response = Mock(status_code=202, headers={'X-Message-Id': 'bulk_id_123'})
        mock_post.return_value = mock_response

        messages = [
            EmailMessageDto(to='user1@example.com', subject='Test 1', body='Body 1'),
            EmailMessageDto(to='user2@example.com', subject='Test 2', body='Body 2'),
            EmailMessageDto(to='user3@example.com', subject='Test 3', body='Body 3'),
        ]

        bulk = BulkEmailDTO(messages=messages)
        result = sendgrid_provider.send_bulk(bulk)

        assert result.total == 3
        assert result.successful == 3
        assert result.failed == 0
        assert len(result.responses) == 3

        # Should call send() for each message
        assert mock_post.call_count == 3

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_bulk_template_emails(self, mock_post, sendgrid_provider):
        """Test sending bulk template emails."""
        mock_response = Mock(status_code=202, headers={'X-Message-Id': 'bulk_template_id'})
        mock_post.return_value = mock_response

        messages = [
            EmailMessageDto(
                to='user1@example.com',
                template_id='d-welcome',
                template_data={'name': 'Alice'}
            ),
            EmailMessageDto(
                to='user2@example.com',
                template_id='d-welcome',
                template_data={'name': 'Bob'}
            ),
            EmailMessageDto(
                to='user3@example.com',
                template_id='d-welcome',
                template_data={'name': 'Charlie'}
            ),
        ]

        bulk = BulkEmailDTO(messages=messages)
        result = sendgrid_provider.send_bulk(bulk)

        assert result.total == 1  # Batched into one request
        assert result.successful == 1
        assert result.failed == 0

        # Should call API once with all personalizations
        assert mock_post.call_count == 1

        # Check payload structure
        payload = mock_post.call_args[1]['json']
        assert payload['template_id'] == 'd-welcome'
        assert len(payload['personalizations']) == 3

        # Check personalizations
        assert payload['personalizations'][0]['to'] == [{'email': 'user1@example.com'}]
        assert payload['personalizations'][0]['dynamic_template_data'] == {'name': 'Alice'}
        assert payload['personalizations'][1]['to'] == [{'email': 'user2@example.com'}]
        assert payload['personalizations'][1]['dynamic_template_data'] == {'name': 'Bob'}

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_bulk_mixed_emails(self, mock_post, sendgrid_provider):
        """Test sending bulk with mix of regular and template emails."""
        mock_response = Mock(status_code=202, headers={'X-Message-Id': 'mixed_id'})
        mock_post.return_value = mock_response

        messages = [
            # Template emails
            EmailMessageDto(to='user1@example.com', template_id='d-welcome', template_data={'name': 'Alice'}),
            EmailMessageDto(to='user2@example.com', template_id='d-welcome', template_data={'name': 'Bob'}),
            # Regular email
            EmailMessageDto(to='admin@example.com', subject='Admin Report', body='Report content'),
        ]

        bulk = BulkEmailDTO(messages=messages)
        result = sendgrid_provider.send_bulk(bulk)

        assert result.total == 2  # 1 batch + 1 regular
        assert result.successful == 2

        # Should call API twice: once for template batch, once for regular
        assert mock_post.call_count == 2

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_bulk_multiple_templates(self, mock_post, sendgrid_provider):
        """Test sending bulk with different template IDs."""
        mock_response = Mock(status_code=202, headers={'X-Message-Id': 'multi_template_id'})
        mock_post.return_value = mock_response

        messages = [
            EmailMessageDto(to='user1@example.com', template_id='d-welcome', template_data={'name': 'Alice'}),
            EmailMessageDto(to='user2@example.com', template_id='d-welcome', template_data={'name': 'Bob'}),
            EmailMessageDto(to='user3@example.com', template_id='d-newsletter', template_data={'month': 'Nov'}),
        ]

        bulk = BulkEmailDTO(messages=messages)
        result = sendgrid_provider.send_bulk(bulk)

        assert result.total == 2  # 2 batches (grouped by template_id)
        assert result.successful == 2

        # Should call API twice: once per template_id
        assert mock_post.call_count == 2

    @patch('mailbridge.providers.sendgrid_provider.requests.post')
    def test_send_bulk_with_defaults(self, mock_post, sendgrid_provider):
        """Test bulk sending with default_from."""
        mock_response = Mock(status_code=202, headers={'X-Message-Id': 'default_id'})
        mock_post.return_value = mock_response

        messages = [
            EmailMessageDto(to='user1@example.com', subject='Test', body='Body'),
            EmailMessageDto(to='user2@example.com', subject='Test', body='Body'),
        ]

        bulk = BulkEmailDTO(
            messages=messages,
            default_from='noreply@example.com'
        )

        result = sendgrid_provider.send_bulk(bulk)

        assert result.successful == 2

        # Check that default_from was applied
        for msg in bulk.messages:
            assert msg.from_email == 'noreply@example.com'

# =============================================================================
# HELPER METHODS TESTS
# =============================================================================

class TestSendGridHelpers:
    """Test helper methods."""

    def test_build_personalizations(self, sendgrid_provider):
        """Test _build_personalizations helper."""
        messages = [
            EmailMessageDto(
                to='user1@example.com',
                template_data={'name': 'Alice'},
                cc=['cc@example.com'],
                subject='Test Subject',
                body='<p>Test body</p>',
            ),
            EmailMessageDto(
                to='user2@example.com',
                template_data={'name': 'Bob'},
                bcc=['bcc@example.com'],
                subject='Test Subject',
                body='<p>Test body</p>',
            ),
        ]

        personalizations = sendgrid_provider._build_personalizations(messages)

        assert len(personalizations) == 2
        assert personalizations[0]['to'] == [{'email': 'user1@example.com'}]
        assert personalizations[0]['dynamic_template_data'] == {'name': 'Alice'}
        assert personalizations[0]['cc'] == [{'email': 'cc@example.com'}]

        assert personalizations[1]['to'] == [{'email': 'user2@example.com'}]
        assert personalizations[1]['bcc'] == [{'email': 'bcc@example.com'}]

    def test_build_payload_regular(self, sendgrid_provider):
        """Test _build_payload for regular email."""
        message = EmailMessageDto(
            to='test@example.com',
            subject='Test Subject',
            body='<p>Test body</p>',
            html=True
        )

        payload = sendgrid_provider._build_payload(message)

        assert payload['from']['email'] == 'sender@example.com'
        assert payload['subject'] == 'Test Subject'
        assert payload['content'][0]['type'] == 'text/html'
        assert payload['content'][0]['value'] == '<p>Test body</p>'

    def test_build_payload_template(self, sendgrid_provider):
        """Test _build_payload for template email."""
        message = EmailMessageDto(
            to='test@example.com',
            template_id='d-template-123',
            template_data={'key': 'value'}
        )

        payload = sendgrid_provider._build_payload(message)

        assert payload['template_id'] == 'd-template-123'
        assert payload['personalizations'][0]['dynamic_template_data'] == {'key': 'value'}
        assert 'subject' not in payload
        assert 'content' not in payload


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestSendGridContextManager:
    """Test context manager support."""

    def test_context_manager(self, sendgrid_config):
        """Test using provider as context manager."""
        with SendGridProvider(**sendgrid_config) as provider:
            assert provider is not None
            assert isinstance(provider, SendGridProvider)


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
