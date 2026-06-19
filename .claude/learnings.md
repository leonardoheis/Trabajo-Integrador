# Classiflow — Design Learnings

Decisions and patterns settled during development that are not obvious from the code alone.
Each entry has a **context**, the **decision**, and the **why**.

---

## Exception style — dataclass subclasses per service

**Context:** `AuditService` needed to surface two distinct failure modes to callers:
missing required fields and a persistence failure from the repository layer.

**Decision:** Each service gets its own `exceptions.py` with:
- A plain base class (e.g. `AuditError(Exception)`)
- `@dataclass` subclasses for each distinct error case, each with typed fields,
  `__post_init__` calling `super().__init__(str(self))`, and `__str__` building the message

```python
from dataclasses import dataclass

class AuditError(Exception): ...

@dataclass
class MissingFieldError(AuditError):
    field: str
    def __post_init__(self) -> None: super().__init__(str(self))
    def __str__(self) -> str: return f"{self.field} is required"

@dataclass
class PersistenceError(AuditError):
    job_id: str
    agent: str
    event: str
    def __post_init__(self) -> None: super().__init__(str(self))
    def __str__(self) -> str:
        return f"Failed to persist for job={self.job_id} agent={self.agent} event={self.event}"
```

**Why:**
- Callers can catch the base class for broad handling or the specific subclass to inspect fields
- `__post_init__` wires `super().__init__` so `str(exc)`, `repr(exc)`, and loguru all work correctly
- Messages live inside the exception class, satisfying ruff rules TRY003 / EM101
- No classmethod factories — those hide the structured data from callers and type checkers

**Do NOT use:**
- Bare `except Exception` — always catch a specific type
- Classmethod factories on a single exception class (e.g. `AuditError.required(...)`)
- `@dataclass` without `__post_init__` calling `super().__init__(str(self))` — `str(exc)` breaks

---

## `__init__` vs `BaseModel` — which to use where

**Context:** Reviewing all `__init__` usages in `src/classiflow/` to check whether any
should be replaced with Pydantic `BaseModel`.

**Decision:** The split is by class role, not by personal preference:

| Role | Pattern | Examples |
|---|---|---|
| Domain / value object | `BaseModel` | `AgentEvent`, `FileReceptionResult`, `User`, `AuthToken` |
| Service / repository | plain `__init__` | `AuditService`, `EventBroadcaster`, `SqlHashRepository`, `InMemoryHashRepository` |

**Why:**
- Services and repositories hold mutable runtime state (`AsyncSession`, `asyncio.Queue`,
  `dict` store) that Pydantic cannot and should not manage.
- Domain objects are pure typed data — Pydantic gives validation, JSON serialization,
  and `model_dump` for free.
- Using `BaseModel` for a service that takes a DB session as a constructor argument
  would break Pydantic's field validation model entirely.

**Rule:** If the class holds a dependency injected at construction (session, repo, queue),
use plain `__init__`. If it is a value that moves between layers, use `BaseModel`.

---

## `__init__.py` content rules (RUF067)

**Context:** `src/classiflow/__init__.py` was calling `configure_container()` at module
level, which caused `ModuleNotFoundError` whenever any `classiflow.*` submodule was imported
during tests.

**Decision:** `__init__.py` files must only contain:
- A `__version__` string (package root only)
- Re-exports (`from .module import Name`)
- `__all__` declarations

No executable statements, no function definitions, no side-effectful calls.

**Why:**
- Python executes `__init__.py` on every `import classiflow.*` — any side effect
  (DB connection, container wiring, network call) runs at import time, including in tests.
- ruff rule RUF067 enforces this and will fail `poe check` if violated.
- `configure_container()` belongs in `create_app()` (T16), not at import time.

**Do NOT put in `__init__.py`:**
```python
# WRONG — runs at import time
configure_container()

# WRONG — function definitions belong in a proper module
def configure_container() -> Container: ...
```

---

## DI container wiring — correct package name and startup timing

**Context:** `injections/__init__.py` contained `container.wire(packages=["app"])`,
a copy-paste artifact from the T01 skeleton template. `"app"` does not exist in this project.

**Decision:**
- Wire target must be `packages=["classiflow"]` (the actual package name).
- `configure_container()` is called once inside `create_app()` (FastAPI app factory, T16),
  never at module import time.
- Until T16 is implemented, `Container` and `TestContainer` remain empty stubs — do not
  add providers to them prematurely.

**Why:** Calling `container.wire()` with a wrong package name raises `ModuleNotFoundError`
at import time and breaks every test that touches any `classiflow.*` module.

---