import asyncio
import base64
from pathlib import Path
from typing import Dict, Any, List
import requests
from mailbridge.providers.base_email_provider import TemplateCapableProvider, BulkCapableProvider
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.exceptions import ConfigurationError, EmailSendError

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


class PostmarkProvider(TemplateCapableProvider, BulkCapableProvider):

    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        try:
            payload = self._build_payload(message)
            headers = self._build_headers()

            response = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code != 200:
                error_data = response.json()
                raise EmailSendError(
                    f"Postmark API error: {error_data.get('ErrorCode')} - "
                    f"{error_data.get('Message')}",
                    provider='postmark'
                )

            result = response.json()

            return EmailResponseDTO(
                success=True,
                message_id=result.get('MessageID'),
                provider='postmark',
                metadata={
                    'submitted_at': result.get('SubmittedAt'),
                    'to': result.get('To'),
                }
            )

        except requests.RequestException as e:
            raise EmailSendError(
                f"Failed to send email via Postmark: {str(e)}",
                provider='postmark',
                original_error=e
            )

    def send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        try:
            responses = []

            for msg in bulk.messages:
                response = self.send(msg)
                responses.append(response)

            return BulkEmailResponseDTO.from_responses(responses)

        except Exception as e:
            raise EmailSendError(
                f"Failed to send bulk emails via Postmark: {str(e)}",
                provider='postmark',
                original_error=e
            )

    async def async_send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send email via Postmark API asynchronously."""
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
                    result = await response.json()

                    if response.status != 200:
                        raise EmailSendError(
                            f"Postmark API error: {result.get('ErrorCode')} - "
                            f"{result.get('Message')}",
                            provider='postmark'
                        )

                    return EmailResponseDTO(
                        success=True,
                        message_id=result.get('MessageID'),
                        provider='postmark',
                        metadata={
                            'submitted_at': result.get('SubmittedAt'),
                            'to': result.get('To'),
                        }
                    )

        except aiohttp.ClientError as e:
            raise EmailSendError(
                f"Failed to send email via Postmark: {str(e)}",
                provider='postmark',
                original_error=e
            )

    async def async_send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        """Send multiple emails via Postmark asynchronously."""
        if not AIOHTTP_AVAILABLE:
            return await super().async_send_bulk(bulk)

        try:
            headers = self._build_headers()

            async with aiohttp.ClientSession() as session:
                tasks = [
                    self._async_send_single(session, headers, msg)
                    for msg in bulk.messages
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            responses = []
            for result in results:
                if isinstance(result, Exception):
                    responses.append(EmailResponseDTO(
                        success=False,
                        provider='postmark',
                        error=str(result)
                    ))
                else:
                    responses.append(result)

            return BulkEmailResponseDTO.from_responses(responses)

        except Exception as e:
            raise EmailSendError(
                f"Failed to send bulk emails via Postmark: {str(e)}",
                provider='postmark',
                original_error=e
            )

    async def _async_send_single(
        self,
        session: 'aiohttp.ClientSession',
        headers: Dict[str, str],
        message: EmailMessageDto
    ) -> EmailResponseDTO:
        """Send a single email using an existing aiohttp session."""
        payload = self._build_payload(message)

        async with session.post(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            result = await response.json()

            if response.status != 200:
                raise EmailSendError(
                    f"Postmark API error: {result.get('ErrorCode')} - "
                    f"{result.get('Message')}",
                    provider='postmark'
                )

            return EmailResponseDTO(
                success=True,
                message_id=result.get('MessageID'),
                provider='postmark',
                metadata={
                    'submitted_at': result.get('SubmittedAt'),
                    'to': result.get('To'),
                }
            )

    def _validate_config(self) -> None:
        """Validate Postmark configuration."""
        if 'server_token' not in self.config:
            raise ConfigurationError(
                "Missing required Postmark configuration: server_token"
            )

        self.endpoint = self.config.get(
            'endpoint',
            'https://api.postmarkapp.com/email'
        )

    def _build_headers(self) -> Dict[str, str]:
        return {
            'X-Postmark-Server-Token': self.config['server_token'],
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _build_payload(self, message: EmailMessageDto) -> Dict[str, Any]:
        payload = {
            'From': message.from_email or self.config.get('from_email'),
            'To': ', '.join(message.to),
            'Subject': message.subject,
        }

        if message.is_template_email():
            payload['TemplateId'] = message.template_id
            payload['TemplateModel'] = message.template_data
        else:
            if message.html:
                payload['HtmlBody'] = message.body
            else:
                payload['TextBody'] = message.body

        if message.cc:
            payload['Cc'] = ', '.join(message.cc)
        if message.bcc:
            payload['Bcc'] = ', '.join(message.bcc)

        if message.reply_to:
            payload['ReplyTo'] = message.reply_to

        if message.headers:
            payload['Headers'] = [
                {'Name': key, 'Value': value}
                for key, value in message.headers.items()
            ]

        if message.attachments:
            payload['Attachments'] = self._build_attachments(message.attachments)

        if self.config.get('track_opens'):
            payload['TrackOpens'] = True
        if self.config.get('track_links'):
            payload['TrackLinks'] = self.config['track_links']

        return payload

    def _build_attachments(self, attachments: List) -> List[Dict[str, str]]:
        result = []

        for attachment in attachments:
            if isinstance(attachment, Path):
                with open(attachment, 'rb') as f:
                    content = base64.b64encode(f.read()).decode()
                result.append({
                    'Name': attachment.name,
                    'Content': content,
                    'ContentType': 'application/octet-stream'
                })
            elif isinstance(attachment, tuple):
                filename, content, mimetype = attachment
                if isinstance(content, str):
                    content = content.encode()
                encoded = base64.b64encode(content).decode()
                result.append({
                    'Name': filename,
                    'Content': encoded,
                    'ContentType': mimetype
                })

        return result
