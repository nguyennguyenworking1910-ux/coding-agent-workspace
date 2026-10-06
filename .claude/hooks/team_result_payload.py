"""Pure payload parsing helpers for team-result hooks.

This module contains no lifecycle mutation, runtime-state mutation,
Merchant authorization, or external side effects.
"""

from __future__ import annotations

import json
from typing import Any


def coalesced_text(
    mapping: dict[str, Any],
    *fields: str,
) -> str:
    """Return one unambiguous non-empty text value across true alias fields."""

    values: list[str] = []

    for field in fields:
        value = mapping.get(field)

        if value is None:
            continue

        text = str(value).strip()

        if text:
            values.append(text)

    if (
        not values
        or any(
            value != values[0]
            for value in values[1:]
        )
    ):
        return ""

    return values[0]


def send_message_body(
    tool_input: dict[str, Any],
) -> str:
    """Return the canonical SendMessage report body."""

    message = tool_input.get("message")

    if isinstance(message, str):
        message = message.strip()

        if message:
            return message

    content = tool_input.get("content")

    if isinstance(content, str):
        return content.strip()

    return ""


def trusted_post_tool_sender(
    payload: dict[str, Any],
) -> str:
    """Return sender only when both harness-authenticated fields are present."""

    agent_id = str(
        payload.get("agent_id")
        or ""
    ).strip()

    agent_type = str(
        payload.get("agent_type")
        or ""
    ).strip()

    if not (
        agent_id
        and agent_type
    ):
        return ""

    return agent_type


def embedded_json_objects(
    text: str,
) -> list[Any]:
    """Return every JSON object embedded in a teammate report body."""

    decoder = json.JSONDecoder()

    objects: list[Any] = []

    index = text.find("{")

    while index != -1:
        try:
            value, end = decoder.raw_decode(
                text,
                index,
            )
        except ValueError:
            index = text.find(
                "{",
                index + 1,
            )
            continue

        if isinstance(value, dict):
            objects.append(value)

            index = text.find(
                "{",
                max(
                    end,
                    index + 1,
                ),
            )
        else:
            index = text.find(
                "{",
                index + 1,
            )

    return objects
