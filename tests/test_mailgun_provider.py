"""
Unit tests for Mailgun provider.

Covers:
- Configuration validation
- Regular email sending
- Template email sending
- Bulk email sending
- Error handling
- Attachments
- CC/BCC/Reply-To

Run with: pytest tests/test_mailgun_provider.py -v
"""

import pytest
from unittest.mock import patch, Mock
from pathlib import Path
import json
import io

from mailbridge.providers.mailgun_provider import MailgunProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.exceptions import ConfigurationError, EmailSendError


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mailgun_config():
    """Valid Mailgun config."""
    return {
        "api_key": "key-test-123",
        "endpoint": "https://api.mailgun.net/v3/example.com",
        "from_email": "no-reply@example.com",
    }


@pytest.fixture
def mailgun_provider(mailgun_config):
    """Provider instance."""
    return MailgunProvider(**mailgun_config)


@pytest.fixture
def simple_message():
    """Simple email message fixture."""
    return EmailMessageDto(
        to="recipient@example.com",
        subject="Mailgun Test",
        body="Hello Mailgun",
        html=False
    )


@pytest.fixture
def template_message():
    """Template-based message."""
    return EmailMessageDto(
        to="recipient@example.com",
        template_id="welcome_template",
        template_data={"name": "John", "promo": "DISCOUNT20"}
    )


@pytest.fixture
def mock_success_response():
    """Mock Mailgun successful response."""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "<20231110@mailgun.org>",
        "message": "Queued. Thank you."
    }
    return mock_resp


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestMailgunConfiguration:

    def test_valid_config(self, mailgun_config):
        provider = MailgunProvider(**mailgun_config)
        assert provider.config["api_key"] == "key-test-123"
        assert provider.endpoint == "https://api.mailgun.net/v3/example.com"

    def test_missing_api_key(self):
        with pytest.raises(ConfigurationError):
            MailgunProvider(endpoint="https://api.mailgun.net/v3/example.com")

    def test_missing_endpoint(self):
        with pytest.raises(ConfigurationError):
            MailgunProvider(api_key="key-xyz")

    def test_context_manager(self, mailgun_config):
        with MailgunProvider(**mailgun_config) as p:
            assert isinstance(p, MailgunProvider)


# =============================================================================
# REGULAR EMAIL TESTS
# =============================================================================

class TestMailgunSend:

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_success(self, mock_post, mailgun_provider, simple_message, mock_success_response):
        mock_post.return_value = mock_success_response

        response = mailgun_provider.send(simple_message)
        assert response.success is True
        assert response.message_id == "<20231110@mailgun.org>"
        assert response.provider == "mailgun"

        args, kwargs = mock_post.call_args
        assert args[0].endswith("/messages")
        assert kwargs["auth"][0] == "api"
        assert kwargs["auth"][1] == "key-test-123"

        data = kwargs["data"]
        assert data["to"] == ["recipient@example.com"]
        assert data["subject"] == "Mailgun Test"
        assert data["text"] == "Hello Mailgun"

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_html_body(self, mock_post, mailgun_provider, mock_success_response):
        mock_post.return_value = mock_success_response
        message = EmailMessageDto(
            to="x@example.com", subject="HTML", body="<h1>Hi</h1>", html=True
        )
        mailgun_provider.send(message)
        data = mock_post.call_args[1]["data"]
        assert "html" in data
        assert data["html"] == "<h1>Hi</h1>"

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_with_cc_bcc_replyto(self, mock_post, mailgun_provider, mock_success_response):
        mock_post.return_value = mock_success_response
        msg = EmailMessageDto(
            to="a@example.com",
            subject="Test",
            body="Body",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            reply_to="reply@example.com"
        )
        mailgun_provider.send(msg)
        data = mock_post.call_args[1]["data"]
        assert data["cc"] == ["cc@example.com"]
        assert data["bcc"] == ["bcc@example.com"]
        assert data["h:Reply-To"] == "reply@example.com"

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_with_headers(self, mock_post, mailgun_provider, mock_success_response):
        mock_post.return_value = mock_success_response
        msg = EmailMessageDto(
            to="x@example.com", subject="Header", body="Body",
            headers={"X-Custom": "Yes"}
        )
        mailgun_provider.send(msg)
        data = mock_post.call_args[1]["data"]
        assert data["h:X-Custom"] == "Yes"

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_api_error(self, mock_post, mailgun_provider, simple_message):
        mock_resp = Mock()
        mock_resp.status_code = 400
        mock_resp.text = "Invalid recipient"
        mock_post.return_value = mock_resp
        with pytest.raises(EmailSendError):
            mailgun_provider.send(simple_message)

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_request_exception(self, mock_post, mailgun_provider, simple_message):
        import requests
        mock_post.side_effect = requests.ConnectionError("Network down")
        with pytest.raises(EmailSendError) as exc:
            mailgun_provider.send(simple_message)
        assert "Mailgun" in str(exc.value)


# =============================================================================
# TEMPLATE EMAIL TESTS
# =============================================================================

class TestMailgunTemplateEmails:

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_template(self, mock_post, mailgun_provider, template_message, mock_success_response):
        mock_post.return_value = mock_success_response
        resp = mailgun_provider.send(template_message)
        assert resp.success is True
        data = mock_post.call_args[1]["data"]
        assert data["template"] == "welcome_template"
        assert json.loads(data["t:variables"]) == {"name": "John", "promo": "DISCOUNT20"}

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_template_empty_data(self, mock_post, mailgun_provider, mock_success_response):
        mock_post.return_value = mock_success_response
        msg = EmailMessageDto(to="x@x.com", template_id="t1", template_data=None)
        mailgun_provider.send(msg)
        data = mock_post.call_args[1]["data"]
        assert json.loads(data["t:variables"]) == {}


# =============================================================================
# ATTACHMENT TESTS
# =============================================================================

class TestMailgunAttachments:

    def test_build_files_from_path(self, mailgun_provider, tmp_path):
        file = tmp_path / "test.txt"
        file.write_text("abc")
        files = mailgun_provider._build_files([file])
        assert len(files) == 1
        assert files[0][0] == "attachment"
        assert files[0][1][0] == "test.txt"

    def test_build_files_from_tuple(self, mailgun_provider):
        content = b"data"
        files = mailgun_provider._build_files([("a.pdf", content, "application/pdf")])
        assert len(files) == 1
        assert files[0][1][0] == "a.pdf"
        assert files[0][1][2] == "application/pdf"


# =============================================================================
# BULK EMAIL TESTS
# =============================================================================

class TestMailgunBulk:

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_bulk_success(self, mock_post, mailgun_provider, mock_success_response):
        mock_post.return_value = mock_success_response
        messages = [
            EmailMessageDto(to=f"user{i}@example.com", subject="S", body="B")
            for i in range(3)
        ]
        bulk = BulkEmailDTO(messages=messages)
        result = mailgun_provider.send_bulk(bulk)
        assert result.total == 3
        assert result.failed == 0
        assert result.successful == 3

    @patch("mailbridge.providers.mailgun_provider.requests.post")
    def test_send_bulk_failure_recorded_per_message(self, mock_post, mailgun_provider):
        """send_bulk records failures per-message instead of raising.
        An unexpected exception from requests is wrapped and recorded as a
        failed response, so the caller gets a BulkEmailResponseDTO with
        failed > 0 rather than an exception propagating out.
        """
        mock_post.side_effect = Exception("unexpected")
        messages = [
            EmailMessageDto(to="x@example.com", subject="S", body="B")
        ]
        bulk = BulkEmailDTO(messages=messages)
        result = mailgun_provider.send_bulk(bulk)
        assert result.total == 1
        assert result.failed == 1
        assert result.successful == 0


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
