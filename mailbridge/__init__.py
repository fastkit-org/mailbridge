"""
MailBridge - Unified email library with multi-provider support.

Synchronous usage:
    from mailbridge import MailBridge

    with MailBridge(provider='sendgrid', api_key='...') as mailer:
        mailer.send(to='user@example.com', subject='Hi', body='Hello!')

Asynchronous usage:
    from mailbridge import AsyncMailBridge

    async with AsyncMailBridge(provider='sendgrid', api_key='...') as mailer:
        await mailer.send(to='user@example.com', subject='Hi', body='Hello!')
"""

# Main clients
from mailbridge.client import MailBridge, AsyncMailBridge

# DTOs
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO

# Exceptions
from mailbridge.exceptions import (
    MailBridgeError,
    ConfigurationError,
    EmailSendError,
    ProviderNotFoundError,
)

__version__ = '2.0.0'

__all__ = [
    # Clients
    'MailBridge',
    'AsyncMailBridge',

    # DTOs
    'EmailMessageDto',
    'EmailResponseDTO',
    'BulkEmailDTO',
    'BulkEmailResponseDTO',

    # Exceptions
    'MailBridgeError',
    'ConfigurationError',
    'EmailSendError',
    'ProviderNotFoundError',
]
