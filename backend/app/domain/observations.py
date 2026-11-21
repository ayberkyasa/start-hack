"""Read-only projections of Target API responses for transcript and replay."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StrictBool, Tag

from app.settings import FrozenModel, Identifier


class RemoteData(BaseModel):
    # Extra wire fields belong to the redacted raw response, outside the UI projection.
    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)


class RemoteEvent(RemoteData):
    id: Identifier
    type: Annotated[str, Field(min_length=1)]
    message_id: Identifier | None = None
    conversation_id: Identifier | None = None


class Reply(RemoteEvent):
    type: Literal["reply"]
    channel: Identifier
    in_reply_to: Identifier | None = None
    subject: str | None = None
    body: str


class LinkOpened(RemoteEvent):
    type: Literal["link.opened"]
    url: str


class PageSubmitted(RemoteEvent):
    type: Literal["page.submitted"]
    page_id: Identifier
    fields: tuple[str, ...]


class AttachmentOpened(RemoteEvent):
    type: Literal["attachment.opened"]
    filename: str | None = None
    asset_id: Identifier | None = None


def _event_tag(value: object) -> str | None:
    tag = value.get("type") if isinstance(value, dict) else getattr(value, "type", None)
    if not isinstance(tag, str) or not tag.strip():
        return None
    if tag in ("reply", "link.opened", "page.submitted", "attachment.opened"):
        return tag
    return "unknown"


ObservedEvent = Annotated[
    Annotated[Reply, Tag("reply")]
    | Annotated[LinkOpened, Tag("link.opened")]
    | Annotated[PageSubmitted, Tag("page.submitted")]
    | Annotated[AttachmentOpened, Tag("attachment.opened")]
    | Annotated[RemoteEvent, Tag("unknown")],
    Discriminator(_event_tag),
]

Count = Annotated[int, Field(strict=True, ge=0)]


class MessageResponse(RemoteData):
    message_id: Identifier
    touches_used: Count
    events: tuple[ObservedEvent, ...]


class GreetingResponse(RemoteData):
    conversation_id: Identifier
    status: Identifier
    persona_says: str
    touches_used: Count


class TurnResponse(RemoteData):
    persona_says: str
    turns_used: Annotated[int, Field(strict=True, ge=1, le=10)]
    ended: StrictBool
    events: tuple[ObservedEvent, ...]


class MessageObservation(FrozenModel):
    kind: Literal["message"]
    response: MessageResponse


class GreetingObservation(FrozenModel):
    kind: Literal["greeting"]
    response: GreetingResponse


class TurnObservation(FrozenModel):
    kind: Literal["turn"]
    conversation_id: Identifier
    response: TurnResponse


ObservationContent = Annotated[
    MessageObservation | GreetingObservation | TurnObservation, Field(discriminator="kind")
]
