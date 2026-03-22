"""SMTP email provider implementation."""
import asyncio
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Dict, Any
from mailbridge.providers.base_email_provider import BaseEmailProvider
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.exceptions import ConfigurationError, EmailSendError

try:
    import aiosmtplib
    AIOSMTPLIB_AVAILABLE = True
except ImportError:
    AIOSMTPLIB_AVAILABLE = False


class SMTPProvider(BaseEmailProvider):

    def _validate_config(self) -> None:
        required = ['host', 'port', 'username', 'password']

        missing = [key for key in required if key not in self.config]

        if missing:
            raise ConfigurationError(
                f"Missing required SMTP configuration: {', '.join(missing)}"
            )

    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        try:
            msg = self._build_mime_message(message)
            recipients = message.to + (message.cc or []) + (message.bcc or [])

            with self._get_smtp_connection() as server:
                server.send_message(msg, to_addrs=recipients)

            return EmailResponseDTO(
                success=True,
                message_id=msg['Message-ID'],
                provider='smtp'
            )

        except Exception as e:
            raise EmailSendError(
                f"Failed to send email via SMTP: {str(e)}",
                provider='smtp',
                original_error=e
            )

    async def async_send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send email via SMTP asynchronously."""
        if not AIOSMTPLIB_AVAILABLE:
            return await super().async_send(message)

        try:
            msg = self._build_mime_message(message)
            recipients = message.to + (message.cc or []) + (message.bcc or [])

            async with self._get_async_smtp_connection() as server:
                await server.send_message(msg, recipients=recipients)

            return EmailResponseDTO(
                success=True,
                message_id=msg['Message-ID'],
                provider='smtp'
            )

        except Exception as e:
            raise EmailSendError(
                f"Failed to send email via SMTP: {str(e)}",
                provider='smtp',
                original_error=e
            )

    async def async_send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        """Send multiple emails via SMTP asynchronously, reusing one connection."""
        if not AIOSMTPLIB_AVAILABLE:
            return await super().async_send_bulk(bulk)

        responses = []

        try:
            async with self._get_async_smtp_connection() as server:
                for message in bulk.messages:
                    try:
                        msg = self._build_mime_message(message)
                        recipients = message.to + (message.cc or []) + (message.bcc or [])
                        await server.send_message(msg, recipients=recipients)
                        responses.append(EmailResponseDTO(
                            success=True,
                            message_id=msg['Message-ID'],
                            provider='smtp'
                        ))
                    except Exception as e:
                        responses.append(EmailResponseDTO(
                            success=False,
                            provider='smtp',
                            error=str(e)
                        ))

        except Exception as e:
            raise EmailSendError(
                f"Failed to send bulk emails via SMTP: {str(e)}",
                provider='smtp',
                original_error=e
            )

        return BulkEmailResponseDTO.from_responses(responses)

    def _build_mime_message(self, message: EmailMessageDto) -> MIMEMultipart:
        """Build a MIME message from an EmailMessageDto."""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = message.subject
        msg['From'] = message.from_email or self.config.get('from_email', self.config['username'])
        msg['To'] = ', '.join(message.to)

        if message.cc:
            msg['Cc'] = ', '.join(message.cc)
        if message.bcc:
            msg['Bcc'] = ', '.join(message.bcc)
        if message.reply_to:
            msg['Reply-To'] = message.reply_to

        if message.headers:
            for key, value in message.headers.items():
                msg[key] = value

        if message.html:
            part = MIMEText(message.body, 'html')
        else:
            part = MIMEText(message.body, 'plain')
        msg.attach(part)

        if message.attachments:
            for attachment in message.attachments:
                self._attach_file(msg, attachment)

        return msg

    def _get_smtp_connection(self):
        use_tls = self.config.get('use_tls', True)
        use_ssl = self.config.get('use_ssl', False)

        if use_ssl:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(
                self.config['host'],
                self.config['port'],
                context=context
            )
        else:
            server = smtplib.SMTP(
                self.config['host'],
                self.config['port']
            )

            if use_tls:
                context = ssl.create_default_context()
                server.starttls(context=context)

        server.login(self.config['username'], self.config['password'])
        return server

    def _get_async_smtp_connection(self):
        """Build an aiosmtplib SMTP context manager."""
        use_tls = self.config.get('use_tls', True)
        use_ssl = self.config.get('use_ssl', False)

        return aiosmtplib.SMTP(
            hostname=self.config['host'],
            port=self.config['port'],
            use_tls=use_ssl,
            start_tls=use_tls and not use_ssl,
            username=self.config['username'],
            password=self.config['password'],
        )

    def _attach_file(self, msg: MIMEMultipart, attachment) -> None:
        if isinstance(attachment, Path):
            with open(attachment, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())

            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename={attachment.name}'
            )
            msg.attach(part)
        elif isinstance(attachment, tuple):
            filename, content, mimetype = attachment
            maintype, subtype = mimetype.split('/', 1)
            part = MIMEBase(maintype, subtype)
            if isinstance(content, str):
                content = content.encode()
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename={filename}'
            )
            msg.attach(part)
