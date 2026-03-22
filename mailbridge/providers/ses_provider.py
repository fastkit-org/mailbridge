import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from mailbridge.providers.base_email_provider import TemplateCapableProvider, BulkCapableProvider
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.exceptions import ConfigurationError, EmailSendError

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


class SESProvider(TemplateCapableProvider, BulkCapableProvider):

    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        try:
            if message.is_template_email():
                return self._send_templated_email(message)
            if message.attachments:
                return self._send_raw_email(message)
            return self._send_simple_email(message)

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            raise EmailSendError(
                f"SES error ({error_code}): {error_message}",
                provider='ses',
                original_error=e
            )
        except (BotoCoreError, Exception) as e:
            raise EmailSendError(
                f"Failed to send email via SES: {str(e)}",
                provider='ses',
                original_error=e
            )

    def send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        try:
            template_messages = [m for m in bulk.messages if m.is_template_email()]
            regular_messages = [m for m in bulk.messages if not m.is_template_email()]

            responses = []

            if template_messages:
                grouped_by_template = {}
                for msg in template_messages:
                    if msg.template_id not in grouped_by_template:
                        grouped_by_template[msg.template_id] = []
                    grouped_by_template[msg.template_id].append(msg)

                for template_id, messages in grouped_by_template.items():
                    for i in range(0, len(messages), 50):
                        batch = messages[i:i + 50]
                        response = self._send_bulk_templated(template_id, batch)
                        responses.append(response)

            for msg in regular_messages:
                response = self.send(msg)
                responses.append(response)

            return BulkEmailResponseDTO.from_responses(responses)

        except Exception as e:
            raise EmailSendError(
                f"Failed to send bulk emails via SES: {str(e)}",
                provider='ses',
                original_error=e
            )

    async def async_send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send email via SES asynchronously.

        boto3 does not provide a native async API, so this runs the
        synchronous send() in a thread pool executor to avoid blocking
        the event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send, message)

    async def async_send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        """Send multiple emails via SES asynchronously.

        Runs individual send() calls concurrently in a thread pool, which
        provides parallelism despite boto3 lacking a native async API.
        """
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(None, self.send, message)
            for message in bulk.messages
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        responses = []
        for result in results:
            if isinstance(result, Exception):
                responses.append(EmailResponseDTO(
                    success=False,
                    provider='ses',
                    error=str(result)
                ))
            else:
                responses.append(result)

        return BulkEmailResponseDTO.from_responses(responses)

    def _validate_config(self) -> None:
        if not BOTO3_AVAILABLE:
            raise ConfigurationError(
                "boto3 is required for SES provider. "
                "Install it with: pip install mailbridge[ses]"
            )

        self.aws_access_key_id = self.config.get('aws_access_key_id')
        self.aws_secret_access_key = self.config.get('aws_secret_access_key')
        self.region_name = self.config.get('region_name', 'us-east-1')

        try:
            session_params = {
                'region_name': self.region_name
            }
            if self.aws_access_key_id and self.aws_secret_access_key:
                session_params['aws_access_key_id'] = self.aws_access_key_id
                session_params['aws_secret_access_key'] = self.aws_secret_access_key

            self.client = boto3.client('ses', **session_params)
        except Exception as e:
            raise ConfigurationError(f"Failed to create SES client: {str(e)}")

    def _send_templated_email(self, message: EmailMessageDto) -> EmailResponseDTO:
        destination = {
            'ToAddresses': message.to
        }

        if message.cc:
            destination['CcAddresses'] = message.cc
        if message.bcc:
            destination['BccAddresses'] = message.bcc

        params = {
            'Source': message.from_email or self.config.get('from_email'),
            'Destination': destination,
            'Template': message.template_id,
            'TemplateData': self._serialize_template_data(message.template_data or {})
        }

        if message.reply_to:
            params['ReplyToAddresses'] = [message.reply_to]

        response = self.client.send_templated_email(**params)

        return EmailResponseDTO(
            success=True,
            message_id=response['MessageId'],
            provider='ses',
            metadata={
                'template_id': message.template_id,
                'request_id': response['ResponseMetadata']['RequestId']
            }
        )

    def _send_bulk_templated(
            self,
            template_id: str,
            messages: List[EmailMessageDto]
    ) -> EmailResponseDTO:
        destinations = []

        for msg in messages:
            destination = {
                'Destination': {
                    'ToAddresses': msg.to
                }
            }

            if msg.template_data:
                destination['ReplacementTemplateData'] = self._serialize_template_data(
                    msg.template_data
                )

            if msg.cc:
                destination['Destination']['CcAddresses'] = msg.cc
            if msg.bcc:
                destination['Destination']['BccAddresses'] = msg.bcc

            destinations.append(destination)

        default_template_data = messages[0].template_data or {}

        params = {
            'Source': messages[0].from_email or self.config.get('from_email'),
            'Template': template_id,
            'DefaultTemplateData': self._serialize_template_data(default_template_data),
            'Destinations': destinations
        }

        response = self.client.send_bulk_templated_email(**params)

        success_count = sum(
            1 for status in response.get('Status', [])
            if status.get('Status') == 'Success'
        )

        return EmailResponseDTO(
            success=True,
            message_id=response['ResponseMetadata']['RequestId'],
            provider='ses',
            metadata={
                'template_id': template_id,
                'bulk_count': len(messages),
                'success_count': success_count,
                'request_id': response['ResponseMetadata']['RequestId']
            }
        )

    def _send_simple_email(self, message: EmailMessageDto) -> EmailResponseDTO:
        destination = {
            'ToAddresses': message.to
        }

        if message.cc:
            destination['CcAddresses'] = message.cc
        if message.bcc:
            destination['BccAddresses'] = message.bcc

        email_message = {
            'Subject': {
                'Data': message.subject,
                'Charset': 'UTF-8'
            },
            'Body': {}
        }

        if message.html:
            email_message['Body']['Html'] = {
                'Data': message.body,
                'Charset': 'UTF-8'
            }
        else:
            email_message['Body']['Text'] = {
                'Data': message.body,
                'Charset': 'UTF-8'
            }

        params = {
            'Source': message.from_email or self.config.get('from_email'),
            'Destination': destination,
            'Message': email_message
        }

        if message.reply_to:
            params['ReplyToAddresses'] = [message.reply_to]

        response = self.client.send_email(**params)

        return EmailResponseDTO(
            success=True,
            message_id=response['MessageId'],
            provider='ses',
            metadata={
                'request_id': response['ResponseMetadata']['RequestId']
            }
        )

    def _send_raw_email(self, message: EmailMessageDto) -> EmailResponseDTO:
        msg = MIMEMultipart()
        msg['Subject'] = message.subject
        msg['From'] = message.from_email or self.config.get('from_email')
        msg['To'] = ', '.join(message.to)

        if message.cc:
            msg['Cc'] = ', '.join(message.cc)
        if message.reply_to:
            msg['Reply-To'] = message.reply_to

        if message.headers:
            for key, value in message.headers.items():
                msg[key] = value

        if message.html:
            part = MIMEText(message.body, 'html', 'utf-8')
        else:
            part = MIMEText(message.body, 'plain', 'utf-8')
        msg.attach(part)

        if message.attachments:
            for attachment in message.attachments:
                self._attach_file(msg, attachment)

        destinations = message.to + (message.cc or []) + (message.bcc or [])

        response = self.client.send_raw_email(
            Source=message.from_email or self.config.get('from_email'),
            Destinations=destinations,
            RawMessage={'Data': msg.as_string()}
        )

        return EmailResponseDTO(
            success=True,
            message_id=response['MessageId'],
            provider='ses',
            metadata={
                'request_id': response['ResponseMetadata']['RequestId']
            }
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

    def _serialize_template_data(self, data: Dict[str, Any]) -> str:
        import json
        return json.dumps(data)
