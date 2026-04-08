"""Pydantic schemas for API validation and serialization."""

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict

from src.models import (
    DebateStatus, ParticipantSide, ParticipantType, 
    InviteTokenStatus
)


# ============== Base Schemas ==============

class DebateBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    proposition: str = Field(..., min_length=10)
    description: Optional[str] = Field(None, max_length=1000)
    max_turn_length: int = Field(default=1000, ge=100, le=5000)
    max_turn_time_seconds: int = Field(default=300, ge=30, le=1800)
    rebuttal_rounds: int = Field(default=2, ge=0, le=5)
    enable_cross_exam: bool = False
    is_public: bool = False


class ParticipantBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    participant_type: ParticipantType = ParticipantType.AGENT
    side: ParticipantSide
    side_order: int = Field(default=0, ge=0)
    agent_provider: Optional[str] = Field(None, max_length=100)


class TurnBase(BaseModel):
    content: str = Field(..., min_length=1)
    replies_to_turn_id: Optional[str] = None


class ScoreBase(BaseModel):
    participant_id: str
    argument_quality: float = Field(..., ge=0, le=10)
    evidence_quality: float = Field(..., ge=0, le=10)
    rebuttal_strength: float = Field(..., ge=0, le=10)
    clarity: float = Field(..., ge=0, le=10)
    compliance: float = Field(..., ge=0, le=10)
    rationale: Optional[str] = Field(None, max_length=2000)
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)


class InviteTokenBase(BaseModel):
    side: ParticipantSide
    participant_type: ParticipantType = ParticipantType.AGENT
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_hours: Optional[int] = Field(default=168, ge=1, le=720)  # 1 week default


# ============== Create Schemas ==============

class DebateCreate(DebateBase):
    created_by: str
    initial_participants: Optional[List[ParticipantBase]] = Field(default_factory=list)


class ParticipantCreate(ParticipantBase):
    debate_id: str


class TurnCreate(TurnBase):
    pass


class InviteTokenCreate(InviteTokenBase):
    created_by: str


class ScoreCreate(ScoreBase):
    pass


# ============== Response Schemas ==============

class ParticipantResponse(ParticipantBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    debate_id: str
    joined_at: datetime
    is_active: bool
    turn_count: int = 0


class TurnResponse(TurnBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    debate_id: str
    participant_id: str
    participant_name: str
    participant_side: ParticipantSide
    sequence_number: int
    phase: DebateStatus
    content_length: int
    submitted_at: datetime
    time_taken_seconds: Optional[int]
    was_timeout: bool
    char_limit_violation: bool


class ScoreResponse(ScoreBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    debate_id: str
    judge_id: str
    judge_name: str
    total_score: float
    weighted_score: float
    created_at: datetime
    version: int


class InviteTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    debate_id: str
    token_preview: str
    side: ParticipantSide
    participant_type: ParticipantType
    max_uses: int
    used_count: int
    status: InviteTokenStatus
    expires_at: Optional[datetime]
    created_at: datetime
    # Only include full token on creation
    token: Optional[str] = None


class DebateResponse(DebateBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    status: DebateStatus
    current_phase: DebateStatus
    current_turn_index: int
    created_at: datetime
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    phase_deadline: Optional[datetime]
    winner_side: Optional[ParticipantSide]
    confidence_score: Optional[float]
    judge_rationale: Optional[str]
    created_by: str
    participants: List[ParticipantResponse] = []
    turns: List[TurnResponse] = []
    turn_count: int = 0


class DebateListResponse(BaseModel):
    id: str
    title: str
    proposition: str
    status: DebateStatus
    created_at: datetime
    participant_count: int
    turn_count: int
    is_public: bool


class DebateResultsResponse(BaseModel):
    debate: DebateResponse
    team_scores: Dict[str, Any]
    individual_scores: List[ScoreResponse]
    winner: Optional[str]
    confidence: float
    rationale: str
    score_breakdown: Dict[str, Any]


# ============== Update Schemas ==============

class DebateUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    status: Optional[DebateStatus] = None


class TurnSubmit(BaseModel):
    content: str = Field(..., min_length=1)
    
    @field_validator('content')
    @classmethod
    def check_unicode_length(cls, v: str) -> str:
        """Validate actual Unicode character count, not byte length."""
        # Count Unicode codepoints (actual characters, not bytes)
        char_count = len(v)
        if char_count > 5000:
            raise ValueError(f"Content exceeds maximum character limit (5000)")
        return v


# ============== WebSocket Schemas ==============

class WebSocketMessage(BaseModel):
    type: str  # 'turn_submitted', 'phase_changed', 'participant_joined', etc.
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TurnOrderItem(BaseModel):
    participant_id: str
    participant_name: str
    side: ParticipantSide
    sequence_number: int
    phase: DebateStatus
    status: str  # 'pending', 'current', 'completed'


class DebateStateUpdate(BaseModel):
    debate_id: str
    status: DebateStatus
    current_phase: DebateStatus
    current_turn: Optional[TurnOrderItem]
    turn_order: List[TurnOrderItem]
    phase_deadline: Optional[datetime]
    recent_turns: List[TurnResponse]


# ============== Join Schemas ==============

class JoinDebateRequest(BaseModel):
    token: str
    name: str = Field(..., min_length=1, max_length=100)
    participant_type: Optional[ParticipantType] = None


class JoinDebateResponse(BaseModel):
    success: bool
    participant_id: Optional[str] = None
    debate_id: Optional[str] = None
    error: Optional[str] = None


# ============== Export Schemas ==============

class DebateExportRequest(BaseModel):
    format: "ExportFormat"
    include_scores: bool = True
    include_turns: bool = True


class DebateExportResponse(BaseModel):
    content: str
    content_type: str
    filename: str


class ExportFormat(str, enum.Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    CSV = "csv"


class DebateExportRequest(BaseModel):
    format: ExportFormat = ExportFormat.MARKDOWN
    include_scores: bool = True
    include_turns: bool = True


class DebateExportResponse(BaseModel):
    content: str
    filename: str
    content_type: str
