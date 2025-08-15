import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from azure.eventhub.exceptions import EventHubError
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TranslationEvent:
    """Data class for translation events"""
    translated_text: str
    source_text: str
    source_language: str
    target_language: str
    confidence_score: Optional[float] = None
    translation_service: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "translated_text": self.translated_text,
            "source_text": self.source_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "confidence_score": self.confidence_score,
            "translation_service": self.translation_service,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "translation"
        }


class EventHubTranslationProducer:
    """Production-ready Event Hub producer for translation streaming"""

    def __init__(self, connection_string: str = None, eventhub_name: str = None):
        self.connection_string = connection_string or os.environ.get('EVENT_HUB_CONNECTION_STR')
        self.eventhub_name = eventhub_name or os.environ.get('EVENT_HUB_NAME')

        if not self.connection_string or not self.eventhub_name:
            raise ValueError("EVENT_HUB_CONNECTION_STR and EVENT_HUB_NAME must be set")

        self._producer = None
        self._stats = {
            "events_sent": 0,
            "batches_sent": 0,
            "errors": 0,
            "start_time": datetime.now(timezone.utc)
        }

    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def connect(self):
        """Initialize the Event Hub producer client"""
        try:
            self._producer = EventHubProducerClient.from_connection_string(
                conn_str=self.connection_string,
                eventhub_name=self.eventhub_name
            )
            logger.info(f"Connected to Event Hub: {self.eventhub_name}")
        except Exception as e:
            logger.error(f"Failed to connect to Event Hub: {e}")
            raise

    async def close(self):
        """Close the producer connection"""
        if self._producer:
            await self._producer.close()
            logger.info("Event Hub connection closed")
            self._log_stats()

    def _log_stats(self):
        """Log producer statistics"""
        duration = (datetime.now(timezone.utc) - self._stats["start_time"]).total_seconds()
        logger.info(f"Session stats - Events: {self._stats['events_sent']}, "
                    f"Batches: {self._stats['batches_sent']}, "
                    f"Errors: {self._stats['errors']}, "
                    f"Duration: {duration:.2f}s")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _send_batch_with_retry(self, batch):
        """Send batch with automatic retry on failure"""
        await self._producer.send_batch(batch)

    async def send_translation_event(self, translation: TranslationEvent):
        """Send a single translation event"""
        await self.send_translation_events([translation])

    async def send_translation_events(self, translations: List[TranslationEvent]):
        """
        Send multiple translation events efficiently using batching

        Args:
            translations: List of TranslationEvent objects
        """
        if not self._producer:
            raise RuntimeError("Producer not connected. Use async context manager or call connect()")

        if not translations:
            logger.warning("No translations to send")
            return

        try:
            # Create batch with partition key for better distribution
            partition_key = f"{translations[0].source_language}-to-{translations[0].target_language}"
            event_data_batch = await self._producer.create_batch(partition_key=partition_key)
            events_in_current_batch = 0

            for translation in translations:
                # Create event data (partition key is set on the batch, not individual events)
                event_data = EventData(body=json.dumps(translation.to_dict()))

                try:
                    event_data_batch.add(event_data)
                    events_in_current_batch += 1

                except ValueError:  # Batch is full
                    # Send current batch and create new one
                    await self._send_batch_with_retry(event_data_batch)
                    self._stats["batches_sent"] += 1
                    self._stats["events_sent"] += events_in_current_batch

                    logger.info(f"Sent batch with {events_in_current_batch} events")

                    # Create new batch with same partition key and add the current event
                    event_data_batch = await self._producer.create_batch(partition_key=partition_key)
                    event_data_batch.add(event_data)
                    events_in_current_batch = 1

            # Send remaining events in the final batch
            if events_in_current_batch > 0:
                await self._send_batch_with_retry(event_data_batch)
                self._stats["batches_sent"] += 1
                self._stats["events_sent"] += events_in_current_batch
                logger.info(f"Sent final batch with {events_in_current_batch} events")

            logger.info(f"Successfully sent {len(translations)} translation events")

        except EventHubError as e:
            self._stats["errors"] += 1
            logger.error(f"Event Hub error: {e}")
            raise
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Unexpected error sending events: {e}")
            raise


# ===========================================
# FOR TESTING: Use the single_translation function
# FOR BATCH PROCESSING: Use the batch translation function
# FOR LIVE SPEECH STREAMING: Use send_live_translation() function below
# ===========================================

async def single_translation():
    """
    FOR TESTING ONLY - Simple test function

    This is just for testing the Event Hub connection.
    For live speech streaming, use send_live_translation() instead.
    """

    translation = TranslationEvent(
        translated_text="Hola mundo",
        source_text="Hello world",
        source_language="en",
        target_language="es",
        confidence_score=0.95,
        translation_service="azure_speech_sdk"
    )

    async with EventHubTranslationProducer() as producer:
        await producer.send_translation_event(translation)


async def batch_translations():
    """
    FOR BATCH PROCESSING ONLY

    Use this if you're processing multiple translations at once
    (e.g., from audio files, document translation, etc.)
    """

    translations = [
        TranslationEvent(
            translated_text="헬로, 월드",
            source_text="Hello world",
            source_language="en",
            target_language="kr",
            confidence_score=0.98,
            translation_service="azure_speech_sdk"
        ),
        TranslationEvent(
            translated_text="Hola mundo",
            source_text="Hello world",
            source_language="en",
            target_language="es",
            confidence_score=0.95,
            translation_service="azure_speech_sdk"
        )
    ]

    async with EventHubTranslationProducer() as producer:
        await producer.send_translation_events(translations)


async def send_live_translation(translation_event):
    """
    USE THIS FUNCTION FOR LIVE SPEECH STREAMING:

    Call this from your Speech SDK callbacks to send translations immediately.
    Keep your Event Hub producer connection open during the session for efficiency.

    """
    try:
        async with EventHubTranslationProducer() as producer:
            await producer.send_translation_event(translation_event)
    except Exception as e:
        logger.error(f"Failed to send live translation: {e}")


# Main function for testing
async def main():
    """Main function for testing the producer"""
    logger.info("Starting translation streaming test...")

    try:
        # Test single translation
        await single_translation()

        # Test batch translations
        await batch_translations()

        logger.info("All tests completed successfully!")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


# ===========================================
# TO RUN THIS CODE

# if __name__ == "__main__":
#    asyncio.run(main())
# ===========================================
