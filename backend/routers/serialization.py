from __future__ import annotations

from typing import Any

from sqlalchemy.inspection import inspect


def serialize_model(instance: Any) -> dict[str, Any]:
    return {
        column.key: getattr(instance, column.key)
        for column in inspect(instance.__class__).mapper.column_attrs
    }


def serialize_models(instances: list[Any]) -> list[dict[str, Any]]:
    return [serialize_model(instance) for instance in instances]
