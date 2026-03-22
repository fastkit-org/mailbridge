from typing import Optional, Dict, Any, Union, List
from pathlib import Path

from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.exceptions import ProviderNotFoundError
from mailbridge.providers.base_email_provider import BaseEmailProvider
from mailbridge.providers.brevo_provider import BrevoProvider
from mailbridge.providers.mailgun_provider import MailgunProvider
from mailbridge.providers.postmark_provider import PostmarkProvider
from mailbridge.providers.sendgrid_provider import SendGridProvider
from mailbridge.providers.ses_provider import SESProvider
from mailbridge.providers.smtp_provider import SMTPProvider


# ---------------------------------------------------------------------------
# Provider registry (shared by both sync and async clients)
# ---------------------------------------------------------------------------

_PROVIDERS: Dict[str, type] = {
    'smtp': SMTPProvider,
    'sendgrid': SendGridProvider,
    'mailgun': MailgunProvider,
    'ses': SESProvider,
    'postmark': PostmarkProvider,
    'brevo': BrevoProvider,
}


def _resolve_provider(provider_name: str, config: dict) -> BaseEmailProvider:
    """Instantiate and return a provider by name."""
    name = provider_name.lower()
    if name not in _PROVIDERS:
        available = ', '.join(_PROVIDERS.keys())
        raise ProviderNotFoundError(
            f"Provider '{provider_name}' not found. Available providers: {available}"
        )
    return _PROVIDERS[name](**config)


# ---------------------------------------------------------------------------
# Synchronous client
# ---------------------------------------------------------------------------

class MailBridge:
    """Synchronous email client with multi-provider support.

    Example:
        with MailBridge(provider='sendgrid', api_key='...') as mailer:
            mailer.send(to='user@example.com', subject='Hi', body='Hello!')
    """

    # Expose the shared registry as a class attribute so existing code that
    # does MailBridge.PROVIDERS still works.
    PROVIDERS = _PROVIDERS

    def __init__(self, provider: str, **config):
        self.provider_name = provider.lower()
        self.provider: BaseEmailProvider = _resolve_provider(provider, config)

    def send(
        self,
        to: Union[str, List[str]],
        subject: Optional[str] = None,
        body: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[Union[str, List[str]]] = None,
        bcc: Optional[Union[str, List[str]]] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Union[Path, tuple]]] = None,
        html: bool = True,
        headers: Optional[Dict[str, str]] = None,
        template_id: Optional[str] = None,
        template_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> EmailResponseDTO:
        """Send an email.

        Args:
            to: Recipient email address(es).
            subject: Email subject (required unless template_id is provided).
            body: Email body, HTML or plain text (required unless template_id is provided).
            from_email: Sender address; falls back to provider config if omitted.
            cc: CC recipients.
            bcc: BCC recipients.
            reply_to: Reply-To address.
            attachments: File paths or (filename, content, mimetype) tuples.
            html: True if body is HTML (default), False for plain text.
            headers: Extra MIME/API headers.
            template_id: Provider template identifier.
            template_data: Variables to interpolate into the template.
            tags: Arbitrary tags passed through to the provider.

        Returns:
            EmailResponseDTO with success flag, message_id, and metadata.

        Raises:
            EmailSendError: If the provider returns an error or the network fails.

        Example:
            >>> mailer.send(
            ...     to='user@example.com',
            ...     subject='Welcome',
            ...     body='<h1>Hello!</h1>',
            ... )
        """
        message = EmailMessageDto(
            to=to,
            subject=subject,
            body=body,
            from_email=from_email,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            attachments=attachments,
            html=html,
            headers=headers,
            template_id=template_id,
            template_data=template_data,
            tags=tags,
        )
        return self.provider.send(message)

    def send_bulk(
        self,
        messages: Union[List[EmailMessageDto], BulkEmailDTO],
        default_from: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> BulkEmailResponseDTO:
        """Send multiple emails at once.

        Args:
            messages: A list of EmailMessageDto objects, or a pre-built BulkEmailDTO.
            default_from: Sender address applied to messages that have none.
            tags: Common tags applied to every message.

        Returns:
            BulkEmailResponseDTO with total / successful / failed counts.

        Example:
            >>> messages = [
            ...     EmailMessageDto(to='a@example.com', subject='Hi', body='Hello A'),
            ...     EmailMessageDto(to='b@example.com', subject='Hi', body='Hello B'),
            ... ]
            >>> result = mailer.send_bulk(messages)
            >>> print(f"Sent: {result.successful}/{result.total}")
        """
        if isinstance(messages, BulkEmailDTO):
            return self.provider.send_bulk(messages)

        bulk = BulkEmailDTO(messages=messages, default_from=default_from, tags=tags)
        return self.provider.send_bulk(bulk)

    def supports_templates(self) -> bool:
        """Return True if the active provider supports template emails."""
        return self.provider.supports_templates()

    def supports_bulk_sending(self) -> bool:
        """Return True if the active provider has a native bulk-send API."""
        return self.provider.supports_bulk_sending()

    def close(self) -> None:
        """Close any open provider connections."""
        self.provider.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # Class-level helpers (shared with AsyncMailBridge via _PROVIDERS)
    # ------------------------------------------------------------------

    @classmethod
    def register_provider(cls, name: str, provider_class: type) -> None:
        """Register a custom provider under the given name.

        The provider class must inherit from BaseEmailProvider.  Once
        registered it is available to both MailBridge and AsyncMailBridge.

        Example:
            >>> class MyProvider(BaseEmailProvider):
            ...     def send(self, message): ...
            >>> MailBridge.register_provider('myprovider', MyProvider)
        """
        if not issubclass(provider_class, BaseEmailProvider):
            raise TypeError(f"{provider_class} must inherit from BaseEmailProvider")
        _PROVIDERS[name.lower()] = provider_class

    @classmethod
    def available_providers(cls) -> List[str]:
        """Return the names of all registered providers."""
        return list(_PROVIDERS.keys())


# ---------------------------------------------------------------------------
# Asynchronous client
# ---------------------------------------------------------------------------

class AsyncMailBridge:
    """Asynchronous email client with multi-provider support.

    Mirrors the MailBridge API exactly, replacing send / send_bulk with
    coroutines.  All providers use native async I/O where available
    (aiohttp for HTTP providers, aiosmtplib for SMTP), and fall back to a
    thread-pool executor for providers without an async SDK (e.g. SES/boto3).

    Example:
        async with AsyncMailBridge(provider='sendgrid', api_key='...') as mailer:
            await mailer.send(to='user@example.com', subject='Hi', body='Hello!')
    """

    # Point to the same shared registry so register_provider works for both.
    PROVIDERS = _PROVIDERS

    def __init__(self, provider: str, **config):
        self.provider_name = provider.lower()
        self.provider: BaseEmailProvider = _resolve_provider(provider, config)

    async def send(
        self,
        to: Union[str, List[str]],
        subject: Optional[str] = None,
        body: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[Union[str, List[str]]] = None,
        bcc: Optional[Union[str, List[str]]] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Union[Path, tuple]]] = None,
        html: bool = True,
        headers: Optional[Dict[str, str]] = None,
        template_id: Optional[str] = None,
        template_data: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> EmailResponseDTO:
        """Send an email asynchronously.

        Accepts exactly the same arguments as MailBridge.send.

        Returns:
            EmailResponseDTO with success flag, message_id, and metadata.

        Raises:
            EmailSendError: If the provider returns an error or the network fails.

        Example:
            >>> await mailer.send(
            ...     to='user@example.com',
            ...     subject='Welcome',
            ...     body='<h1>Hello!</h1>',
            ... )
        """
        message = EmailMessageDto(
            to=to,
            subject=subject,
            body=body,
            from_email=from_email,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            attachments=attachments,
            html=html,
            headers=headers,
            template_id=template_id,
            template_data=template_data,
            tags=tags,
        )
        return await self.provider.async_send(message)

    async def send_bulk(
        self,
        messages: Union[List[EmailMessageDto], BulkEmailDTO],
        default_from: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> BulkEmailResponseDTO:
        """Send multiple emails asynchronously.

        Accepts the same arguments as MailBridge.send_bulk.

        Returns:
            BulkEmailResponseDTO with total / successful / failed counts.

        Example:
            >>> messages = [
            ...     EmailMessageDto(to='a@example.com', subject='Hi', body='Hello A'),
            ...     EmailMessageDto(to='b@example.com', subject='Hi', body='Hello B'),
            ... ]
            >>> result = await mailer.send_bulk(messages)
            >>> print(f"Sent: {result.successful}/{result.total}")
        """
        if isinstance(messages, BulkEmailDTO):
            return await self.provider.async_send_bulk(messages)

        bulk = BulkEmailDTO(messages=messages, default_from=default_from, tags=tags)
        return await self.provider.async_send_bulk(bulk)

    def supports_templates(self) -> bool:
        """Return True if the active provider supports template emails."""
        return self.provider.supports_templates()

    def supports_bulk_sending(self) -> bool:
        """Return True if the active provider has a native bulk-send API."""
        return self.provider.supports_bulk_sending()

    async def close(self) -> None:
        """Close any open async provider connections."""
        await self.provider.async_close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ------------------------------------------------------------------
    # Class-level helpers (delegate to MailBridge so registry is shared)
    # ------------------------------------------------------------------

    @classmethod
    def register_provider(cls, name: str, provider_class: type) -> None:
        """Register a custom provider.  See MailBridge.register_provider."""
        MailBridge.register_provider(name, provider_class)

    @classmethod
    def available_providers(cls) -> List[str]:
        """Return the names of all registered providers."""
        return list(_PROVIDERS.keys())
