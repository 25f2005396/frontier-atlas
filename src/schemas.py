from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(BaseModel):
    name: str
    url: str


# ---------- Startup ----------
class StartupData(BaseModel):
    employeeCount: Optional[int] = Field(None, ge=0)


class StartupContent(BaseModel):
    entityName: str
    data: StartupData = StartupData()


class StartupRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["STARTUP"] = "STARTUP"
    source: Source
    content: StartupContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- Product ----------
class PricingModel(str, Enum):
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


class ProductContent(BaseModel):
    startupName: str
    productName: str
    pricingModel: Optional[PricingModel] = None


class ProductRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["PRODUCT"] = "PRODUCT"
    source: Source
    content: ProductContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- Research paper ----------
class PaperContent(BaseModel):
    title: str
    authors: list[str]
    paper_url: str
    github_url: Optional[str] = None
    github_stars: Optional[int] = Field(None, ge=0)
    github_stars_fetched_at: Optional[datetime] = None
    github_link_confidence: Optional[str] = None  # "high" = release phrase near link, "low" = link only mentioned
    published_date: datetime


class ResearchPaperRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    source: Source
    content: PaperContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- Job ----------
class JobContent(BaseModel):
    company: str
    title: str
    date: datetime
    is_remote: bool
    role_family: str


class JobRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["JOB"] = "JOB"
    source: Source
    content: JobContent
    collectedAt: datetime = Field(default_factory=utcnow)


# ---------- News ----------
class NewsContent(BaseModel):
    title: str
    published_at: datetime
    full_text: str


class NewsRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: Literal["NEWS"] = "NEWS"
    source: Source
    content: NewsContent
    collectedAt: datetime = Field(default_factory=utcnow)