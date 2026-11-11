import json
import logging
from datetime import UTC, datetime

from docksight.application.redaction import Redactor
from docksight.domain.diagnostics import JsonObject


class JsonAudit:
    """Mirror committed action audit through the redacted application logger."""

    def __init__(self, redactor: Redactor) -> None:
        """Bind the redactor used for every audit record."""
        self.logger = logging.getLogger("docksight.audit")
        self.redactor = redactor

    async def record(self, event: str, data: JsonObject) -> None:
        """Write one sanitized mirror event whose failure cannot undo authoritative storage."""
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
