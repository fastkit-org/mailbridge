import asyncio
import json
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


class MailgunProvider(TemplateCapableProvider, BulkCapableProvider):

    def _validate_config(self) -> None:
        required = ['api_key', 'endpoint']
        missing = [key for key in required if key not in self.config]
        if missing:
            raise ConfigurationError(
                f"Missing required Mailgun configuration: {', '.join(missing)}"
            )
        self.endpoint = self.config['endpoint']

    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        try:
            data = self._build_form_data(message)
            files = self._build_files(message.attachments) if message.attachments else None
            auth = ('api', self.config['api_key'])

            response = requests.post(
                f"{self.endpoint}/messages",
                auth=auth,
                data=data,
                files=files,
                timeout=30
            )

            if response.status_code != 200:
                raise EmailSendError(
                    f"Mailgun API error: {response.status_code} - {response.text}",
                    provider='mailgun'
                )

            result = response.json()

            return EmailResponseDTO(
                success=True,
                message_id=result.get('id'),
                provider='mailgun',
                metadata={'message': result.get('message')}
            )

        except requests.RequestException as e:
            raise EmailSendError(
                f"Failed to send email via Mailgun: {str(e)}",
                provider='mailgun',
                original_error=e
            )

    def send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        responses = []

        for msg in bulk.messages:
            try:
                responses.append(self.send(msg))
            except EmailSendError as e:
                responses.append(EmailResponseDTO(
                    success=False,
                    provider='mailgun',
                    error=str(e)
                ))
            except Exception as e:
                responses.append(EmailResponseDTO(
                    success=False,
                    provider='mailgun',
                    error=f"Unexpected error: {str(e)}"
                ))

        return BulkEmailResponseDTO.from_responses(responses)

    async def async_send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send email via Mailgun API asynchronously."""
        if not AIOHTTP_AVAILABLE:
            return await super().async_send(message)

        try:
            form_data = self._build_aiohttp_form_data(message)
            auth = aiohttp.BasicAuth('api', self.config['api_key'])

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.endpoint}/messages",
                    data=form_data,
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise EmailSendError(
                            f"Mailgun API error: {response.status} - {text}",
                            provider='mailgun'
                        )

                    result = await response.json()

                    return EmailResponseDTO(
                        success=True,
                        message_id=result.get('id'),
                        provider='mailgun',
                        metadata={'message': result.get('message')}
                    )

        except aiohttp.ClientError as e:
            raise EmailSendError(
                f"Failed to send email via Mailgun: {str(e)}",
                provider='mailgun',
                original_error=e
            )

    async def async_send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        """Send multiple emails via Mailgun asynchronously."""
        if not AIOHTTP_AVAILABLE:
            return await super().async_send_bulk(bulk)

        try:
            auth = aiohttp.BasicAuth('api', self.config['api_key'])

            async with aiohttp.ClientSession() as session:
                tasks = [
                    self._async_send_single(session, auth, msg)
                    for msg in bulk.messages
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            responses = []
            for result in results:
                if isinstance(result, Exception):
                    responses.append(EmailResponseDTO(
                        success=False,
                        provider='mailgun',
                        error=str(result)
                    ))
                else:
                    responses.append(result)

            return BulkEmailResponseDTO.from_responses(responses)

        except Exception as e:
            raise EmailSendError(
                f"Failed to send bulk emails via Mailgun: {str(e)}",
                provider='mailgun',
                original_error=e
            )

    async def _async_send_single(
        self,
        session: 'aiohttp.ClientSession',
        auth: 'aiohttp.BasicAuth',
        message: EmailMessageDto
    ) -> EmailResponseDTO:
        """Send a single email using an existing aiohttp session."""
        form_data = self._build_aiohttp_form_data(message)

        async with session.post(
            f"{self.endpoint}/messages",
            data=form_data,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise EmailSendError(
                    f"Mailgun API error: {response.status} - {text}",
                    provider='mailgun'
                )

            result = await response.json()

            return EmailResponseDTO(
                success=True,
                message_id=result.get('id'),
                provider='mailgun',
                metadata={'message': result.get('message')}
            )

    def _build_aiohttp_form_data(self, message: EmailMessageDto) -> 'aiohttp.FormData':
        """Build an aiohttp FormData object from a message."""
        data = self._build_form_data(message)
        form_data = aiohttp.FormData()

        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    form_data.add_field(key, item)
            else:
                form_data.add_field(key, str(value))

        if message.attachments:
            for attachment in message.attachments:
                if isinstance(attachment, Path):
                    with open(attachment, 'rb') as f:
                        form_data.add_field(
                            'attachment',
                            f.read(),
                            filename=attachment.name,
                            content_type='application/octet-stream'
                        )
                elif isinstance(attachment, tuple):
                    filename, content, mimetype = attachment
                    if isinstance(content, str):
                        content = content.encode()
                    form_data.add_field(
                        'attachment',
                        content,
                        filename=filename,
                        content_type=mimetype
                    )

        return form_data

    def _build_form_data(self, message: EmailMessageDto) -> Dict[str, Any]:
        """Build the dict of form fields for a Mailgun request."""
        data: Dict[str, Any] = {
            'from': message.from_email or self.config.get('from_email'),
            'to': message.to,
            'subject': message.subject,
        }

        if message.is_template_email():
            data['template'] = message.template_id
            data['recipient-variables'] = json.dumps(message.template_data or {})
            data['t:variables'] = json.dumps(message.template_data or {})
        else:
            if message.html:
                data['html'] = message.body
            else:
                data['text'] = message.body

        if message.cc:
            data['cc'] = message.cc
        if message.bcc:
            data['bcc'] = message.bcc
        if message.reply_to:
            data['h:Reply-To'] = message.reply_to
        if message.headers:
            for key, value in message.headers.items():
                data[f'h:{key}'] = value

        return data

    def _build_files(self, attachments: List) -> List[tuple]:
        """Build the files list for a requests multipart POST."""
        files = []

        for attachment in attachments:
            if isinstance(attachment, Path):
                files.append((
                    'attachment',
                    (attachment.name, open(attachment, 'rb'), 'application/octet-stream')
                ))
            elif isinstance(attachment, tuple):
                filename, content, mimetype = attachment
                if isinstance(content, str):
                    content = content.encode()
                files.append(('attachment', (filename, content, mimetype)))

        return files
