"""API schemas speak camelCase on the wire, snake_case in Python."""

from __future__ import annotations

from ninja import Schema
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel


class CamelSchema(Schema):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class Ok(CamelSchema):
    ok: bool = True
