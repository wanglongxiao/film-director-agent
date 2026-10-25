"""Pydantic models for the movie script agent API."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, Field
import config

TextModel = Annotated[
    Literal["deepseek-1017", "seed-sc-0215"],
    BeforeValidator(config.normalize_text_model),
]


class Character(BaseModel):
    name: str = ""
    role: str = ""          # protagonist / supporting / antagonist
    background: str = ""
    personality: str = ""
    arc: str = ""           # authenticity / complexity of human nature


class Storyboard(BaseModel):
    shot: str = ""          # visual / storyboard description
    scene: str = ""         # scene setting (location, time, atmosphere)
    dialogue: str = ""      # character dialogue / actions in this shot
    image_url: str = ""     # generated image URL (Seedream)


class Episode(BaseModel):
    number: int
    title: str = ""
    synopsis: str = ""
    storyboards: list[Storyboard] = Field(default_factory=list)


class Chapter(BaseModel):
    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    synopsis: str = Field(min_length=1)
    content: str = ""
    summary: str = ""               # actual plot/continuity after writing


class Novel(BaseModel):
    title: str = Field(min_length=1)
    # Keep existing archived manuscripts readable; new requests use current limits.
    chapters_count: int = Field(
        default=config.GENERATION_SETTINGS["chapters_count"]["default"],
        ge=3, le=config.GENERATION_SETTINGS["chapters_count"]["max"],
    )
    chapter_length: int = Field(
        default=config.GENERATION_SETTINGS["chapter_length"]["default"],
        ge=800, le=config.GENERATION_SETTINGS["chapter_length"]["max"],
    )
    chapters: list[Chapter] = Field(default_factory=list)

class WritingSettings(BaseModel):
    chapters_count: int = Field(
        default=config.GENERATION_SETTINGS["chapters_count"]["default"],
        ge=config.GENERATION_SETTINGS["chapters_count"]["min"],
        le=config.GENERATION_SETTINGS["chapters_count"]["max"],
    )
    chapter_length: int = Field(
        default=config.GENERATION_SETTINGS["chapter_length"]["default"],
        ge=config.GENERATION_SETTINGS["chapter_length"]["min"],
        le=config.GENERATION_SETTINGS["chapter_length"]["max"],
    )


class SessionState(BaseModel):
    title: str = ""                  # work title shared by discussion, prose and history
    stage: str = "background"
    language: str = "zh-CN"          # zh-CN / zh-TW / en / ja / ko
    text_model: TextModel = config.DEFAULT_TEXT_MODEL
    genre: str = ""                  # horror / romance / historical / ...
    tone: str = ""
    background: str = ""
    characters: list[Character] = Field(default_factory=list)
    outline: str = ""
    style: str = ""                  # chinese / hollywood
    rating: str = ""                 # 7+ / 12+ / 18+
    script_type: str = ""            # film / tv_series / short_drama
    episodes: list[Episode] = Field(default_factory=list)
    novel: Novel | None = None
    writing: WritingSettings = Field(default_factory=WritingSettings)
    discussion_chapters: list[Chapter] = Field(default_factory=list)


# --- API request / response models ---


class SessionCreate(BaseModel):
    language: str = "zh-CN"
    text_model: TextModel = config.DEFAULT_TEXT_MODEL


class ModelRequest(BaseModel):
    text_model: TextModel = config.DEFAULT_TEXT_MODEL


class SessionOut(BaseModel):
    session_id: str
    state: SessionState


class ChatRequest(WritingSettings):
    message: str


class ChatResponse(BaseModel):
    reply: str
    state: SessionState


class EpisodeRequest(BaseModel):
    number: int = Field(default=1, ge=1)
    storyboards_count: int = Field(default=12, ge=1, le=60)
    with_images: bool = True


class NovelRequest(WritingSettings):
    pass


class EpisodeResponse(BaseModel):
    episode: Episode
    state: SessionState


class ReferenceImage(BaseModel):
    kind: str        # "character" | "scene"
    title: str
    prompt: str
    image_url: str = ""
    character_name: str = ""


class ReferenceRequest(BaseModel):
    total: int = Field(
        default=config.GENERATION_SETTINGS["images_count"]["default"],
        ge=config.GENERATION_SETTINGS["images_count"]["min"],
        le=config.GENERATION_SETTINGS["images_count"]["max"],
    )


class ReferenceResponse(BaseModel):
    images: list[ReferenceImage] = Field(default_factory=list)
