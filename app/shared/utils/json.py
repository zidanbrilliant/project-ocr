import json
from datetime import datetime
from typing import Any
from uuid import UUID


class AIJSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> str:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def dumps(obj: Any, **kwargs) -> str:
    return json.dumps(obj, cls=AIJSONEncoder, **kwargs)


def loads(s: str) -> Any:
    return json.loads(s)
