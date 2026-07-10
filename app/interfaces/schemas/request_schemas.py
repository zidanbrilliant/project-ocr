from pydantic import BaseModel, Field


class ReprocessRequest(BaseModel):
    reason: str = Field(default="")
    force: bool = Field(default=False)
