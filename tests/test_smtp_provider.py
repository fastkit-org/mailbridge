"""
Unit tests for SMTP provider.

Tests cover:
- Configuration validation
- Regular email sending
- Plain text vs HTML
- CC/BCC/Reply-To
- Attachments
- TLS vs SSL connections
- Error handling
- Message-ID generation
- MIME structure correctness
- Content-Disposition filename encoding
- Plain-text fallback for HTML messages

Run with: pytest tests/test_smtp_provider.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import smtplib

from mailbridge.providers.smtp_provider import SMTPProvider, _html_to_plain
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.exceptions import ConfigurationError, EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def smtp_config():
    """SMTP configuration fixture."""
    return {
        'host': 'smtp.example.com',
        'port': 587,
        'username': 'user@example.com',
        'password': 'password123',
        'from_email': 'sender@example.com',
        'use_tls': True,
        'use_ssl': False
    }


@pytest.fixture
def smtp_provider(smtp_config):
    """SMTP provider fixture."""
    return SMTPProvider(**smtp_config)


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
def mock_smtp_server():
    """Mock SMTP server."""
    mock_server = MagicMock()
    mock_server.__enter__ = Mock(return_value=mock_server)
    mock_server.__exit__ = Mock(return_value=False)
    return mock_server


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestSMTPConfiguration:
    """Test SMTP provider configuration."""

    def test_valid_configuration(self, smtp_config):
        """Test provider initializes with valid config."""
        provider = SMTPProvider(**smtp_config)

        assert provider.config['host'] == 'smtp.example.com'
        assert provider.config['port'] == 587
        assert provider.config['username'] == 'user@example.com'
        assert provider.config['use_tls'] is True

    def test_missing_required_config(self):
        """Test provider raises error when required config is missing."""
        with pytest.raises(ConfigurationError) as exc_info:
            SMTPProvider(host='smtp.example.com', port=587)

        assert 'username' in str(exc_info.value)
        assert 'password' in str(exc_info.value)

    def test_supports_templates(self, smtp_provider):
        """Test SMTP provider does NOT support templates."""
        assert smtp_provider.supports_templates() is False

    def test_supports_bulk_sending(self, smtp_provider):
        """Test SMTP provider does NOT have native bulk."""
        assert smtp_provider.supports_bulk_sending() is False


# =============================================================================
# REGULAR EMAIL TESTS
# =============================================================================

class TestSMTPRegularEmail:
    """Test regular email sending."""

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_simple_email(self, mock_smtp_class, smtp_provider, simple_message):
        """Test sending a simple email via SMTP."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        response = smtp_provider.send(simple_message)

        # Check response
        assert response.success is True
        assert response.provider == 'smtp'

        # Check SMTP connection
        mock_smtp_class.assert_called_once_with('smtp.example.com', 587)
        # Check message was sent
        mock_server.send_message.assert_called_once()

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP_SSL')
    def test_send_with_ssl(self, mock_smtp_ssl_class, smtp_config):
        """Test sending email with SSL connection."""
        smtp_config['use_ssl'] = True
        smtp_config['use_tls'] = False
        provider = SMTPProvider(**smtp_config)

        mock_server = MagicMock()
        mock_smtp_ssl_class.return_value.__enter__.return_value = mock_server

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='SSL Test',
            body='Body'
        )

        response = provider.send(message)

        assert response.success is True

        # Should use SMTP_SSL
        mock_smtp_ssl_class.assert_called_once()

        # Should NOT call starttls (already SSL)
        mock_server.starttls.assert_not_called()

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_plain_text(self, mock_smtp_class, smtp_provider):
        """Test sending plain text email."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Plain Text',
            body='Plain text content',
            html=False
        )

        response = smtp_provider.send(message)

        assert response.success is True

        # Check message was sent
        call_args = mock_server.send_message.call_args
        sent_message = call_args[0][0]

        # Check it's plain text (would need to parse MIME to verify fully)
        assert sent_message['Subject'] == 'Plain Text'

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_with_cc_bcc(self, mock_smtp_class, smtp_provider):
        """Test sending email with CC and BCC."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Body',
            cc=['cc@example.com'],
            bcc=['bcc@example.com']
        )

        response = smtp_provider.send(message)

        assert response.success is True

        # Check recipients include to, cc, bcc
        call_kwargs = mock_server.send_message.call_args[1]
        recipients = call_kwargs['to_addrs']
        assert 'recipient@example.com' in recipients
        assert 'cc@example.com' in recipients
        assert 'bcc@example.com' in recipients

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_with_reply_to(self, mock_smtp_class, smtp_provider):
        """Test sending email with Reply-To."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Body',
            reply_to='reply@example.com'
        )

        response = smtp_provider.send(message)

        assert response.success is True

        sent_message = mock_server.send_message.call_args[0][0]
        assert sent_message['Reply-To'] == 'reply@example.com'

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_with_custom_headers(self, mock_smtp_class, smtp_provider):
        """Test sending email with custom headers."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Body',
            headers={'X-Custom-Header': 'custom-value', 'X-Priority': '1'}
        )

        response = smtp_provider.send(message)

        assert response.success is True

        sent_message = mock_server.send_message.call_args[0][0]
        assert sent_message['X-Custom-Header'] == 'custom-value'
        assert sent_message['X-Priority'] == '1'

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_with_attachments(self, mock_smtp_class, smtp_provider, tmp_path):
        """Test sending email with file attachment."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='With Attachment',
            body='See attached',
            attachments=[test_file]
        )

        response = smtp_provider.send(message)

        assert response.success is True

        # Message was sent (attachment is in MIME message)
        mock_server.send_message.assert_called_once()

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_with_tuple_attachment(self, mock_smtp_class, smtp_provider):
        """Test sending email with tuple attachment."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        attachment = ('report.csv', b'col1,col2\nval1,val2', 'text/csv')

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='CSV Report',
            body='Report attached',
            attachments=[attachment]
        )

        response = smtp_provider.send(message)

        assert response.success is True
        mock_server.send_message.assert_called_once()

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_connection_error(self, mock_smtp_class, smtp_provider, simple_message):
        """Test handling of SMTP connection error."""
        mock_smtp_class.side_effect = smtplib.SMTPConnectError(421, b'Service not available')

        with pytest.raises(EmailSendError) as exc_info:
            smtp_provider.send(simple_message)

        assert 'Failed to send email via SMTP' in str(exc_info.value)


# =============================================================================
# CONNECTION TESTS
# =============================================================================

class TestSMTPConnection:
    """Test SMTP connection handling."""

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_get_smtp_connection_tls(self, mock_smtp_class, smtp_config):
        """Test SMTP connection with TLS."""
        smtp_config['use_tls'] = True
        smtp_config['use_ssl'] = False
        provider = SMTPProvider(**smtp_config)

        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        connection = provider._get_smtp_connection()

        # Should create SMTP (not SMTP_SSL)
        mock_smtp_class.assert_called_once_with('smtp.example.com', 587)

        # Should call STARTTLS
        mock_server.starttls.assert_called_once()

        # Should login
        mock_server.login.assert_called_once_with('user@example.com', 'password123')

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP_SSL')
    def test_get_smtp_connection_ssl(self, mock_smtp_ssl_class, smtp_config):
        """Test SMTP connection with SSL."""
        smtp_config['use_ssl'] = True
        smtp_config['use_tls'] = False
        provider = SMTPProvider(**smtp_config)

        mock_server = MagicMock()
        mock_smtp_ssl_class.return_value = mock_server

        connection = provider._get_smtp_connection()

        # Should create SMTP_SSL
        mock_smtp_ssl_class.assert_called_once()

        # Should NOT call starttls
        mock_server.starttls.assert_not_called()

        # Should login
        mock_server.login.assert_called_once()

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_default_from_email(self, mock_smtp_class, smtp_config):
        """Test using default from_email when not specified in message."""
        provider = SMTPProvider(**smtp_config)

        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        message = EmailMessageDto(
            to='recipient@example.com',
            subject='Test',
            body='Body',
            from_email=None  # Not specified
        )

        response = provider.send(message)

        assert response.success is True

        sent_message = mock_server.send_message.call_args[0][0]
        # Should use from_email from config
        assert sent_message['From'] == 'sender@example.com'


# =============================================================================
# HELPER METHODS TESTS
# =============================================================================

class TestSMTPHelpers:
    """Test helper methods."""

    def test_attach_file(self, smtp_provider, tmp_path):
        """Test _attach_file with Path object."""
        from email.mime.multipart import MIMEMultipart

        test_file = tmp_path / "document.txt"
        test_file.write_text("Content")

        msg = MIMEMultipart()
        smtp_provider._attach_file(msg, test_file)

        # Check attachment was added
        assert len(msg.get_payload()) == 1

    def test_attach_tuple(self, smtp_provider):
        """Test _attach_file with tuple."""
        from email.mime.multipart import MIMEMultipart

        attachment = ('file.csv', b'data', 'text/csv')

        msg = MIMEMultipart()
        smtp_provider._attach_file(msg, attachment)

        # Check attachment was added
        assert len(msg.get_payload()) == 1


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestSMTPContextManager:
    """Test context manager support."""

    def test_context_manager(self, smtp_config):
        """Test using provider as context manager."""
        with SMTPProvider(**smtp_config) as provider:
            assert provider is not None
            assert isinstance(provider, SMTPProvider)


# =============================================================================
# MESSAGE-ID TESTS
# =============================================================================

class TestSMTPMessageId:
    """Test that Message-ID is always generated and returned in the response."""

    def test_build_mime_message_sets_message_id(self, smtp_provider, simple_message):
        """_build_mime_message always sets a non-empty Message-ID header."""
        msg = smtp_provider._build_mime_message(simple_message)

        assert msg['Message-ID'] is not None
        assert len(msg['Message-ID']) > 0

    def test_message_id_is_unique_per_message(self, smtp_provider, simple_message):
        """Each call to _build_mime_message produces a different Message-ID."""
        msg1 = smtp_provider._build_mime_message(simple_message)
        msg2 = smtp_provider._build_mime_message(simple_message)

        assert msg1['Message-ID'] != msg2['Message-ID']

    def test_message_id_format(self, smtp_provider, simple_message):
        """Message-ID follows the RFC 2822 angle-bracket format."""
        msg = smtp_provider._build_mime_message(simple_message)
        message_id = msg['Message-ID']

        assert message_id.startswith('<')
        assert message_id.endswith('>')
        assert '@' in message_id

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_response_contains_message_id(self, mock_smtp_class, smtp_provider, simple_message):
        """send() returns a response whose message_id is populated."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        response = smtp_provider.send(simple_message)

        assert response.message_id is not None
        assert response.message_id.startswith('<')
        assert '@' in response.message_id

    @patch('mailbridge.providers.smtp_provider.smtplib.SMTP')
    def test_send_bulk_responses_contain_message_ids(self, mock_smtp_class, smtp_provider):
        """send_bulk() populates message_id on every successful response."""
        from mailbridge.dto.bulk_email_dto import BulkEmailDTO

        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        messages = [
            EmailMessageDto(to=f'u{i}@example.com', subject=f'Test {i}', body='Body')
            for i in range(3)
        ]
        result = smtp_provider.send_bulk(BulkEmailDTO(messages=messages))

        for response in result.responses:
            assert response.success is True
            assert response.message_id is not None
            assert '@' in response.message_id

# =============================================================================
# MIME STRUCTURE TESTS
# =============================================================================

class TestSMTPMimeStructure:
    """Verify the MIME tree is correct with and without attachments."""

    def test_no_attachments_outer_is_alternative(self, smtp_provider):
        """Without attachments the outer container is multipart/alternative."""
        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello</p>',
            html=True,
        )
        msg = smtp_provider._build_mime_message(message)

        assert msg.get_content_type() == 'multipart/alternative'

    def test_with_attachments_outer_is_mixed(self, smtp_provider, tmp_path):
        """With attachments the outer container is multipart/mixed."""
        attachment = tmp_path / 'f.txt'
        attachment.write_text('data')

        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello</p>',
            html=True,
            attachments=[attachment],
        )
        msg = smtp_provider._build_mime_message(message)

        assert msg.get_content_type() == 'multipart/mixed'

    def test_with_attachments_first_part_is_alternative(self, smtp_provider, tmp_path):
        """With attachments the first child of mixed must be multipart/alternative."""
        attachment = tmp_path / 'f.txt'
        attachment.write_text('data')

        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello</p>',
            html=True,
            attachments=[attachment],
        )
        msg = smtp_provider._build_mime_message(message)
        parts = msg.get_payload()

        assert parts[0].get_content_type() == 'multipart/alternative'

    def test_with_attachments_second_part_is_attachment(self, smtp_provider, tmp_path):
        """With attachments the second child of mixed is the attachment part."""
        attachment = tmp_path / 'f.txt'
        attachment.write_text('data')

        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello</p>',
            html=True,
            attachments=[attachment],
        )
        msg = smtp_provider._build_mime_message(message)
        parts = msg.get_payload()

        assert parts[1].get_content_maintype() == 'application'
        assert parts[1].get_filename() == 'f.txt'

    def test_multiple_attachments_all_present(self, smtp_provider, tmp_path):
        """All attachments appear as separate parts inside multipart/mixed."""
        files = []
        for name in ('a.txt', 'b.txt', 'c.txt'):
            f = tmp_path / name
            f.write_text('data')
            files.append(f)

        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='Body',
            attachments=files,
        )
        msg = smtp_provider._build_mime_message(message)
        parts = msg.get_payload()

        # First part is the body block, rest are attachments
        assert len(parts) == 4
        filenames = [p.get_filename() for p in parts[1:]]
        assert set(filenames) == {'a.txt', 'b.txt', 'c.txt'}

# =============================================================================
# PLAIN-TEXT FALLBACK TESTS
# =============================================================================

class TestSMTPPlainTextFallback:
    """Verify that HTML messages always carry a plain-text alternative."""

    def _get_body_alternative_parts(self, msg):
        """Return the list of parts inside the (possibly nested) alternative block."""
        if msg.get_content_type() == 'multipart/alternative':
            return msg.get_payload()
        # Has attachments — alternative is nested as the first child of mixed
        return msg.get_payload()[0].get_payload()

    def test_html_message_has_plain_and_html_parts(self, smtp_provider):
        """HTML message contains both text/plain fallback and text/html part."""
        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello <b>World</b></p>',
            html=True,
        )
        msg = smtp_provider._build_mime_message(message)
        parts = self._get_body_alternative_parts(msg)

        content_types = [p.get_content_type() for p in parts]
        assert 'text/plain' in content_types
        assert 'text/html' in content_types

    def test_html_part_is_last(self, smtp_provider):
        """HTML part comes after plain-text per RFC 2046 §5.1.4 (best last)."""
        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello</p>',
            html=True,
        )
        msg = smtp_provider._build_mime_message(message)
        parts = self._get_body_alternative_parts(msg)

        assert parts[-1].get_content_type() == 'text/html'
        assert parts[0].get_content_type() == 'text/plain'

    def test_html_body_preserved_in_html_part(self, smtp_provider):
        """The text/html part carries the original HTML body unchanged."""
        body = '<p>Hello <b>World</b></p>'
        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body=body,
            html=True,
        )
        msg = smtp_provider._build_mime_message(message)
        parts = self._get_body_alternative_parts(msg)

        html_part = next(p for p in parts if p.get_content_type() == 'text/html')
        assert body in html_part.get_payload(decode=True).decode()

    def test_plain_fallback_strips_html_tags(self, smtp_provider):
        """The text/plain fallback contains visible text without HTML tags."""
        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>Hello <b>World</b></p>',
            html=True,
        )
        msg = smtp_provider._build_mime_message(message)
        parts = self._get_body_alternative_parts(msg)

        plain_part = next(p for p in parts if p.get_content_type() == 'text/plain')
        plain_text = plain_part.get_payload(decode=True).decode()

        assert 'Hello' in plain_text
        assert 'World' in plain_text
        assert '<' not in plain_text
        assert '>' not in plain_text

    def test_plain_only_message_has_single_part(self, smtp_provider):
        """Plain-text message has only a text/plain part — no unnecessary wrapping."""
        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='Just plain text',
            html=False,
        )
        msg = smtp_provider._build_mime_message(message)
        # The outer alternative container itself holds exactly one part
        parts = msg.get_payload()

        assert len(parts) == 1
        assert parts[0].get_content_type() == 'text/plain'

    def test_html_message_with_attachment_has_plain_fallback(self, smtp_provider, tmp_path):
        """Plain-text fallback is present even when the message also has attachments."""
        attachment = tmp_path / 'doc.txt'
        attachment.write_text('data')

        message = EmailMessageDto(
            to='r@example.com',
            subject='Test',
            body='<p>See attachment</p>',
            html=True,
            attachments=[attachment],
        )
        msg = smtp_provider._build_mime_message(message)
        # Outer is mixed; first child is the alternative block
        alternative_block = msg.get_payload()[0]
        content_types = [p.get_content_type() for p in alternative_block.get_payload()]

        assert 'text/plain' in content_types
        assert 'text/html' in content_types


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
