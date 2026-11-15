from pydantic import BaseModel, Field
class JobInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int
    params: dict = Field(default_factory=dict)
class ReviewNote(BaseModel):
    """Optional body for approve / withdraw / resubmit actions.

    version is the review_version the reviewer saw; when it no longer matches,
    the action is rejected instead of silently applying to another revision.
    """
    reason: str = Field(default='', max_length=500)
    note: str = Field(default='', max_length=500)
    version: int | None = None
