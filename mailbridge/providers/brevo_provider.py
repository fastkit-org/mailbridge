import asyncio
import base64
from pathlib import Path
from typing import Dict, Any, List
import requests
from mailbridge.providers.base_email_provider import TemplateCapableProvider, BulkCapableProvider
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.exceptions import ConfigurationError, EmailSendError

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


class BrevoProvider(TemplateCapableProvider, BulkCapableProvider):
    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        try:
            payload = self._build_payload(message)
            response = self._send_request(payload)
            result = response.json()

            return EmailResponseDTO(
                success=True,
                message_id=result.get('messageId'),
                provider='brevo',
                metadata={
                    'status_code': response.status_code
                }
            )

        except requests.RequestException as e:
            raise EmailSendError(
                f"Failed to send email via Brevo: {str(e)}",
                provider='brevo',
                original_error=e
            )

    def send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        try:
            payload = {
                'sender': {
                    'email': bulk.default_from or self.config.get('from_email')
                },
                'subject': bulk.messages[0].subject,
                'messageVersions': []
            }

            for message in bulk.messages:
                message_payload = self._build_payload(message, True)
                message_payload['to'] = [{'email': email} for email in message.to]
                payload['messageVersions'].append(message_payload)

            response = self._send_request(payload)
            result = response.json()

            email_responses = []
            for message_id in result.get('messageId'):
                email_responses.append(EmailResponseDTO(
                    success=True,
                    message_id=message_id,
                    provider='brevo',
                    metadata={
                        'status_code': response.status_code
                    }
                ))

            return BulkEmailResponseDTO.from_responses(email_responses)

        except requests.RequestException as e:
            raise EmailSendError(
                f"Failed to send email via Brevo: {str(e)}",
                provider='brevo',
                original_error=e
            )

    async def async_send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send email via Brevo API asynchronously."""
        if not AIOHTTP_AVAILABLE:
            return await super().async_send(message)

        try:
            payload = self._build_payload(message)
            headers = self._build_headers()

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status not in (200, 201):
                        error_data = await response.json()
                        raise EmailSendError(
                            f"Brevo API error: {error_data.get('code')} - "
                            f"{error_data.get('message')}",
                            provider='brevo'
                        )

                    result = await response.json()

                    return EmailResponseDTO(
                        success=True,
                        message_id=result.get('messageId'),
                        provider='brevo',
                        metadata={'status_code': response.status}
                    )

        except aiohttp.ClientError as e:
            raise EmailSendError(
                f"Failed to send email via Brevo: {str(e)}",
                provider='brevo',
                original_error=e
            )

    async def async_send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        """Send multiple emails via Brevo asynchronously using batch endpoint."""
        if not AIOHTTP_AVAILABLE:
            return await super().async_send_bulk(bulk)

        try:
            payload = {
                'sender': {
                    'email': bulk.default_from or self.config.get('from_email')
                },
                'subject': bulk.messages[0].subject,
                'messageVersions': []
            }

            for message in bulk.messages:
                message_payload = self._build_payload(message, is_bulk=True)
                message_payload['to'] = [{'email': email} for email in message.to]
                payload['messageVersions'].append(message_payload)

            headers = self._build_headers()

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status not in (200, 201):
                        error_data = await response.json()
                        raise EmailSendError(
                            f"Brevo API error: {error_data.get('code')} - "
                            f"{error_data.get('message')}",
                            provider='brevo'
                        )

                    result = await response.json()

            email_responses = [
                EmailResponseDTO(
                    success=True,
                    message_id=message_id,
                    provider='brevo',
                    metadata={'status_code': response.status}
                )
                for message_id in result.get('messageId', [])
            ]

            return BulkEmailResponseDTO.from_responses(email_responses)

        except aiohttp.ClientError as e:
            raise EmailSendError(
                f"Failed to send bulk emails via Brevo: {str(e)}",
                provider='brevo',
                original_error=e
            )

    def _validate_config(self) -> None:
        """Validate Brevo configuration."""
        if 'api_key' not in self.config:
            raise ConfigurationError(
                "Missing required Brevo configuration: api_key"
            )

        self.endpoint = self.config.get(
            'endpoint',
            'https://api.brevo.com/v3/smtp/email'
        )

    def _build_headers(self) -> Dict[str, str]:
        return {
            'api-key': self.config['api_key'],
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _send_request(self, payload: Dict[str, Any]):
        response = requests.post(
            self.endpoint,
            json=payload,
            headers=self._build_headers(),
            timeout=30
        )

        if response.status_code not in (200, 201):
            error_data = response.json()
            raise EmailSendError(
                f"Brevo API error: {error_data.get('code')} - "
                f"{error_data.get('message')}",
                provider='brevo'
            )

        return response

    def _build_payload(self, message: EmailMessageDto, is_bulk: bool = False) -> Dict[str, Any]:

        if not is_bulk:
            payload = {
                'sender': {
                    'email': message.from_email or self.config.get('from_email')
                },
                'to': [{'email': email} for email in message.to],
                'subject': message.subject,
            }
        else:
            payload = {}

        if message.is_template_email():
            payload['templateId'] = message.template_id
            payload['params'] = message.template_data or {}
        else:
            if message.html:
                payload['htmlContent'] = message.body
            else:
                payload['textContent'] = message.body

        if message.cc:
            payload['cc'] = [{'email': email} for email in message.cc]

        if message.bcc:
            payload['bcc'] = [{'email': email} for email in message.bcc]

        if message.reply_to:
            payload['replyTo'] = {'email': message.reply_to}

        if message.headers:
            payload['headers'] = message.headers

        if message.attachments:
            payload['attachment'] = self._build_attachments(message.attachments)

        if self.config.get('tags'):
            payload['tags'] = self.config['tags']

        return payload

    def _build_attachments(self, attachments: List) -> List[Dict[str, str]]:
        result = []

        for attachment in attachments:
            if isinstance(attachment, Path):
                with open(attachment, 'rb') as f:
                    content = base64.b64encode(f.read()).decode()
                result.append({
                    'name': attachment.name,
                    'content': content
                })
            elif isinstance(attachment, tuple):
                filename, content, mimetype = attachment
                if isinstance(content, str):
                    content = content.encode()
                encoded = base64.b64encode(content).decode()
                result.append({
                    'name': filename,
                    'content': encoded
                })

        return result
