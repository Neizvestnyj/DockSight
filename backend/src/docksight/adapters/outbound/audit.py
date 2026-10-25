import json
import logging
from datetime import UTC, datetime

from docksight.application.redaction import Redactor
from docksight.domain.diagnostics import JsonObject


class JsonAudit:
    """Emit redacted action audit records through the application logger."""

    def __init__(self, redactor: Redactor) -> None:
        """Bind the redactor used for every audit record."""
        self.logger = logging.getLogger("docksight.audit")
        self.redactor = redactor

    async def record(self, event: str, data: JsonObject) -> None:
        """Write one structured audit event after sanitizing its content."""
        self.logger.info(
            self.redactor.text(
                json.dumps(
                    {
                        "event": event,
                        "time": datetime.now(UTC).isoformat(),
                        **data,
                    }
                )
            )
        )
