from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

ConfigT = TypeVar("ConfigT", bound=BaseModel)


def load_yaml_config(path: Path, model: type[ConfigT]) -> ConfigT:
    return model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
