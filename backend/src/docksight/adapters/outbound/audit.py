import json
import logging
from datetime import UTC, datetime

from docksight.application.redaction import Redactor
from docksight.domain.diagnostics import JsonObject


class JsonAudit:
    def __init__(self, redactor: Redactor) -> None:
        self.logger = logging.getLogger("docksight.audit")
        self.redactor = redactor

    async def record(self, event: str, data: JsonObject) -> None:
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
