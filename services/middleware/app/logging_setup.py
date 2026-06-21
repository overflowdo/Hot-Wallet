import logging
from pythonjsonlogger import jsonlogger

class ContextFilter(logging.Filter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        # guarantee fields exist (avoid KeyError in formatter)
        if not hasattr(record, "service"):
            record.service = self.service
        if not hasattr(record, "intent_id"):
            record.intent_id = ""
        if not hasattr(record, "txid"):
            record.txid = ""
        if not hasattr(record, "request_id"):
            record.request_id = ""
        return True

def setup_logging(service: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(service)s %(intent_id)s %(txid)s %(request_id)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter(service))

    root.handlers = [handler]

    # keep uvicorn logs usable
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
