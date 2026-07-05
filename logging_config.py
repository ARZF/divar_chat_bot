import contextvars
import json
import logging
from datetime import datetime, timezone


DEFAULT_CONTEXT_VALUE = "-"


client_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "client_id",
    default=DEFAULT_CONTEXT_VALUE,
)

conversation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "conversation_id",
    default=DEFAULT_CONTEXT_VALUE,
)


STANDARD_LOG_RECORD_FIELDS = (
    set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
    | {"message", "asctime"}
)


class ContextFilter(logging.Filter):
    """
    Inject request context into every log record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.client_id = client_id_var.get()
        record.conversation_id = conversation_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    """
    Format log records as structured JSON.
    """

    CONTEXT_FIELDS = {"client_id", "conversation_id"}

    def format(self, record: logging.LogRecord) -> str:
        payload = self._build_payload(record)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)

    def _build_payload(self, record: logging.LogRecord) -> dict:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "client_id": getattr(record, "client_id", DEFAULT_CONTEXT_VALUE),
            "conversation_id": getattr(
                record,
                "conversation_id",
                DEFAULT_CONTEXT_VALUE,
            ),
        }

        payload.update(self._extract_extra_fields(record))
        return payload

    def _extract_extra_fields(self, record: logging.LogRecord) -> dict:
        return {
            key: value
            for key, value in record.__dict__.items()
            if key not in STANDARD_LOG_RECORD_FIELDS
            and key not in self.CONTEXT_FIELDS
        }


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(ContextFilter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)