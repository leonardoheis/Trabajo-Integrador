from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from classiflow.domain.base import BaseEntity


class JobContext(BaseEntity):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
    )
    job_id: str
    filename: str
