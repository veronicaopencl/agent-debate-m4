"""SQLAlchemy models for Agent Debate system."""

import enum
import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, Text, 
    Enum, Float, Boolean, Index, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from src.database import Base


def generate_uuid() -> str:
    """Generate a unique identifier."""
    return str(uuid.uuid4())


class DebateStatus(str, enum.Enum):
    """Debate state machine states."""
    PENDING = "pending"           # Waiting to start
    OPENING = "opening"           # Opening statements
    REBUTTAL_1 = "rebuttal_1"     # First rebuttal round
    REBUTTAL_2 = "rebuttal_2"     # Second rebuttal round (optional)
    CROSS_EXAM = "cross_exam"     # Cross examination (optional)
    CLOSING = "closing"           # Final statements
    JUDGING = "judging"           # Judging phase
    COMPLETE = "complete"         # Debate finished
    CANCELLED = "cancelled"       # Cancelled


class ParticipantSide(str, enum.Enum):
    """Which side of the debate."""
    PRO = "pro"
    CON = "con"
    JUDGE = "judge"
    OBSERVER = "observer"


class ParticipantType(str, enum.Enum):
    """Type of participant."""
    HUMAN = "human"
    AGENT = "agent"


class InviteTokenStatus(str, enum.Enum):
    """Status of an invite token."""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Debate(Base):
    """A debate session."""
    __tablename__ = "debates"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=False)
    proposition = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    
    # Configuration
    max_turn_length = Column(Integer, default=1000)  # Characters
    max_turn_time_seconds = Column(Integer, default=300)  # 5 minutes
    rebuttal_rounds = Column(Integer, default=2)
    enable_cross_exam = Column(Boolean, default=False)
    
    # State machine
    status = Column(Enum(DebateStatus), default=DebateStatus.PENDING, nullable=False)
    current_phase = Column(Enum(DebateStatus), default=DebateStatus.PENDING)
    current_turn_index = Column(Integer, default=0)
    
    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    phase_deadline = Column(DateTime(timezone=True), nullable=True)
    
    # Results
    winner_side = Column(Enum(ParticipantSide), nullable=True)
    confidence_score = Column(Float, nullable=True)  # 0-1, avoiding fake certainty
    judge_rationale = Column(Text, nullable=True)
    
    # Metadata
    created_by = Column(String(255), nullable=False)
    is_public = Column(Boolean, default=False)
    metadata_json = Column(JSON, default=dict)
    
    # Relationships
    participants = relationship("Participant", back_populates="debate", cascade="all, delete-orphan")
    turns = relationship("Turn", back_populates="debate", cascade="all, delete-orphan", order_by="Turn.sequence_number")
    scores = relationship("Score", back_populates="debate", cascade="all, delete-orphan")
    invite_tokens = relationship("InviteToken", back_populates="debate", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_debate_status', 'status'),
        Index('idx_debate_created', 'created_at'),
    )


class Participant(Base):
    """A participant in a debate."""
    __tablename__ = "participants"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    debate_id = Column(String(36), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False)
    
    # Identity
    name = Column(String(100), nullable=False)
    participant_type = Column(Enum(ParticipantType), default=ParticipantType.AGENT)
    side = Column(Enum(ParticipantSide), nullable=False)
    
    # Ordering within side (for turn order)
    side_order = Column(Integer, default=0)
    
    # External agent info
    agent_id = Column(String(255), nullable=True)  # External agent identifier
    agent_provider = Column(String(100), nullable=True)  # e.g., "openai", "anthropic"
    
    # Join info
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    invite_token_id = Column(String(36), ForeignKey("invite_tokens.id"), nullable=True)
    
    # State
    is_active = Column(Boolean, default=True)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    debate = relationship("Debate", back_populates="participants")
    turns = relationship("Turn", back_populates="participant")
    scores_given = relationship("Score", foreign_keys="Score.judge_id", back_populates="judge")
    scores_received = relationship("Score", foreign_keys="Score.participant_id", back_populates="participant")
    invite_token = relationship("InviteToken", back_populates="participant")
    
    __table_args__ = (
        Index('idx_participant_debate', 'debate_id'),
        Index('idx_participant_side', 'debate_id', 'side'),
    )


class Turn(Base):
    """A single turn/speech in a debate."""
    __tablename__ = "turns"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    debate_id = Column(String(36), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False)
    participant_id = Column(String(36), ForeignKey("participants.id"), nullable=False)
    
    # Ordering
    sequence_number = Column(Integer, nullable=False)
    phase = Column(Enum(DebateStatus), nullable=False)
    
    # Content
    content = Column(Text, nullable=False)
    content_length = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    time_taken_seconds = Column(Integer, nullable=True)
    
    # Validation
    was_timeout = Column(Boolean, default=False)
    char_limit_violation = Column(Boolean, default=False)
    
    # Rebuttal tracking
    replies_to_turn_id = Column(String(36), ForeignKey("turns.id"), nullable=True)
    
    # Metadata
    metadata_json = Column(JSON, default=dict)
    
    # Relationships
    debate = relationship("Debate", back_populates="turns")
    participant = relationship("Participant", back_populates="turns")
    replies_to = relationship("Turn", remote_side=[id])
    
    __table_args__ = (
        Index('idx_turn_debate_seq', 'debate_id', 'sequence_number'),
        Index('idx_turn_participant', 'participant_id'),
        Index('idx_turn_phase', 'debate_id', 'phase'),
    )
    
    @validates('content')
    def validate_content(self, key, content):
        """Auto-calculate content length."""
        self.content_length = len(content) if content else 0
        return content


class Score(Base):
    """Judge scoring for a participant."""
    __tablename__ = "scores"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    debate_id = Column(String(36), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False)
    participant_id = Column(String(36), ForeignKey("participants.id"), nullable=False)
    judge_id = Column(String(36), ForeignKey("participants.id"), nullable=False)
    
    # Rubric scores (0-10 each)
    argument_quality = Column(Float, nullable=False)
    evidence_quality = Column(Float, nullable=False)
    rebuttal_strength = Column(Float, nullable=False)
    clarity = Column(Float, nullable=False)
    compliance = Column(Float, nullable=False)
    
    # Calculated
    total_score = Column(Float, nullable=False)
    weighted_score = Column(Float, nullable=False)
    
    # Commentary
    rationale = Column(Text, nullable=True)
    strengths = Column(JSON, default=list)
    weaknesses = Column(JSON, default=list)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_json = Column(JSON, default=dict)
    
    # Tamper detection
    version = Column(Integer, default=1)
    previous_hash = Column(String(64), nullable=True)
    
    # Relationships
    debate = relationship("Debate", back_populates="scores")
    participant = relationship("Participant", foreign_keys=[participant_id], back_populates="scores_received")
    judge = relationship("Participant", foreign_keys=[judge_id], back_populates="scores_given")
    
    __table_args__ = (
        Index('idx_score_debate', 'debate_id'),
        Index('idx_score_participant', 'participant_id'),
        Index('idx_score_judge', 'judge_id'),
        # BLOCKER FIX #3: Unique constraint prevents duplicate judge scoring
        UniqueConstraint('debate_id', 'judge_id', 'participant_id', name='uq_score_judge_participant'),
    )


class InviteToken(Base):
    """Token for inviting participants to a debate."""
    __tablename__ = "invite_tokens"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    debate_id = Column(String(36), ForeignKey("debates.id", ondelete="CASCADE"), nullable=False)
    
    # Token value (hashed for storage)
    token_hash = Column(String(64), nullable=False, index=True)
    token_preview = Column(String(8), nullable=False)  # First 8 chars for display
    
    # Configuration
    side = Column(Enum(ParticipantSide), nullable=False)
    participant_type = Column(Enum(ParticipantType), default=ParticipantType.AGENT)
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    
    # Status
    status = Column(Enum(InviteTokenStatus), default=InviteTokenStatus.ACTIVE)
    
    # Expiry
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Usage tracking
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(255), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    
    # Rate limiting
    ip_addresses = Column(JSON, default=list)  # Track IPs that attempted use
    
    # Relationships
    debate = relationship("Debate", back_populates="invite_tokens")
    participant = relationship("Participant", back_populates="invite_token", uselist=False)
    
    __table_args__ = (
        Index('idx_token_hash', 'token_hash'),
        Index('idx_token_debate', 'debate_id'),
    )


class AuditLog(Base):
    """Audit log for security and debugging."""
    __tablename__ = "audit_logs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    debate_id = Column(String(36), ForeignKey("debates.id", ondelete="SET NULL"), nullable=True)
    
    # Event info
    event_type = Column(String(50), nullable=False)
    event_data = Column(JSON, default=dict)
    
    # Actor
    actor_type = Column(String(20), nullable=False)  # 'system', 'user', 'agent'
    actor_id = Column(String(255), nullable=True)
    
    # Context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        Index('idx_audit_debate', 'debate_id'),
        Index('idx_audit_event', 'event_type'),
        Index('idx_audit_timestamp', 'timestamp'),
    )
