import asyncio
from abc import ABC, abstractmethod

from mailbridge.dto.bulk_email_dto import BulkEmailDTO
from mailbridge.dto.bulk_email_response_dto import BulkEmailResponseDTO
from mailbridge.dto.email_message_dto import EmailMessageDto
from mailbridge.dto.email_response_dto import EmailResponseDTO
from mailbridge.exceptions import EmailSendError


class BaseEmailProvider(ABC):
    def __init__(self, **config):
        self.config = config
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """Validate required configuration parameters."""
        pass

    @abstractmethod
    def send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send an email through this provider."""
        pass

    def send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        responses = []

        for message in bulk.messages:
            try:
                responses.append(self.send(message))
            except EmailSendError as e:
                responses.append(EmailResponseDTO(
                    success=False,
                    provider=self.__class__.__name__,
                    error=str(e)
                ))
            except Exception as e:
                responses.append(EmailResponseDTO(
                    success=False,
                    provider=self.__class__.__name__,
                    error=f"Unexpected error: {str(e)}"
                ))
        return BulkEmailResponseDTO.from_responses(responses)

    async def async_send(self, message: EmailMessageDto) -> EmailResponseDTO:
        """Send an email asynchronously.

        Default implementation runs the synchronous send() in a thread pool.
        Providers with native async HTTP clients should override this method.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send, message)

    async def async_send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        """Send multiple emails asynchronously.

        Default implementation runs the synchronous send_bulk() in a thread pool.
        Providers with native async HTTP clients should override this method.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send_bulk, bulk)

    def supports_templates(self) -> bool:
        return False

    def supports_bulk_sending(self) -> bool:
        return False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup connections."""
        self.close()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup connections."""
        await self.async_close()

    def close(self) -> None:
        """Close any open connections. Override if needed."""
        pass

    async def async_close(self) -> None:
        """Close any open async connections. Override if needed."""
        self.close()


class TemplateCapableProvider(BaseEmailProvider, ABC):
    def supports_templates(self) -> bool:
        return True


class BulkCapableProvider(BaseEmailProvider):
    def supports_bulk_sending(self) -> bool:
        return True

    @abstractmethod
    def send_bulk(self, bulk: BulkEmailDTO) -> BulkEmailResponseDTO:
        pass
