import logging
import json
import contextvars
from datetime import datetime, timezone

client_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("client_id", default="-")
conversation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("conversation_id", default="-")

# Standard LogRecord attributes — anything NOT in this set was added via extra={...}
_STANDARD_ATTRS = set(logging.LogRecord(
    "", 0, "", 0, "", (), None
).__dict__.keys()) | {"message", "asctime"}

class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.client_id = client_id_var.get()
        record.conversation_id = conversation_id_var.get()
        return True

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "client_id": getattr(record, "client_id", "-"),
            "conversation_id": getattr(record, "conversation_id", "-"),
        }
        # Pull in anything passed via extra={...} that isn't a standard LogRecord field
        # (client_id/conversation_id already handled above, so skip those to avoid dupes)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in ("client_id", "conversation_id"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)