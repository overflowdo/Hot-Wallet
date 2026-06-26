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
        return True

def setup_logging(service: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(service)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter(service))

    root.handlers = [handler]

    # keep uvicorn logs usable
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
