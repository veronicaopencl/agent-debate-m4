"""Debate state machine with strict turn management."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from src.models import (
    Debate, DebateStatus, Participant, ParticipantSide, 
    Turn, Score, AuditLog
)
from src.database import get_db_session


class StateMachineError(Exception):
    """Error in state machine operation."""
    pass


class InvalidTurnError(StateMachineError):
    """Invalid turn submission."""
    pass


class StateTransitionError(StateMachineError):
    """Invalid state transition."""
    pass


class DebateStateMachine:
    """
    Manages debate state transitions and turn order.
    
    State flow:
    PENDING → OPENING → REBUTTAL_1 → [REBUTTAL_2] → [CROSS_EXAM] → CLOSING → JUDGING → COMPLETE
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        DebateStatus.PENDING: [DebateStatus.OPENING, DebateStatus.CANCELLED],
        DebateStatus.OPENING: [DebateStatus.REBUTTAL_1, DebateStatus.CANCELLED],
        DebateStatus.REBUTTAL_1: [DebateStatus.REBUTTAL_2, DebateStatus.CROSS_EXAM, DebateStatus.CLOSING, DebateStatus.CANCELLED],
        DebateStatus.REBUTTAL_2: [DebateStatus.CROSS_EXAM, DebateStatus.CLOSING, DebateStatus.CANCELLED],
        DebateStatus.CROSS_EXAM: [DebateStatus.CLOSING, DebateStatus.CANCELLED],
        DebateStatus.CLOSING: [DebateStatus.JUDGING, DebateStatus.CANCELLED],
        DebateStatus.JUDGING: [DebateStatus.COMPLETE, DebateStatus.CANCELLED],
        DebateStatus.COMPLETE: [],
        DebateStatus.CANCELLED: [],
    }
    
    # Phase durations (seconds) - configurable per debate
    DEFAULT_PHASE_DURATIONS = {
        DebateStatus.OPENING: 600,      # 10 min for opening statements
        DebateStatus.REBUTTAL_1: 300,    # 5 min per rebuttal
        DebateStatus.REBUTTAL_2: 300,
        DebateStatus.CROSS_EXAM: 420,    # 7 min for cross-exam
        DebateStatus.CLOSING: 600,       # 10 min for closing
        DebateStatus.JUDGING: 1800,      # 30 min for judging
    }
    
    def __init__(self, debate_id: str, db: Optional[Session] = None):
        self.debate_id = debate_id
        self.db = db or get_db_session()
        self._debate: Optional[Debate] = None
        self._turn_order: List[Dict[str, Any]] = []
        self._current_turn_index: int = 0
    
    def _get_debate(self) -> Debate:
        """Get debate with fresh data."""
        if self._debate is None:
            self._debate = self.db.query(Debate).filter(Debate.id == self.debate_id).first()
            if not self._debate:
                raise StateMachineError(f"Debate {self.debate_id} not found")
        return self._debate
    
    def _audit_log(self, event_type: str, event_data: dict, actor_type: str = "system", actor_id: Optional[str] = None):
        """Create audit log entry."""
        log = AuditLog(
            debate_id=self.debate_id,
            event_type=event_type,
            event_data=event_data,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        self.db.add(log)
        self.db.commit()
    
    def get_participants_by_side(self, side: ParticipantSide) -> List[Participant]:
        """Get active participants on a given side."""
        debate = self._get_debate()
        return [
            p for p in debate.participants 
            if p.side == side and p.is_active
        ]
    
    def build_turn_order(self) -> List[Dict[str, Any]]:
        """
        Build the complete turn order for the debate.
        
        Pattern: Alternating sides, respecting side_order within each side.
        """
        debate = self._get_debate()
        
        # Get active debaters (not judges/observers)
        pro_debaters = sorted(
            [p for p in debate.participants if p.side == ParticipantSide.PRO and p.is_active],
            key=lambda p: p.side_order
        )
        con_debaters = sorted(
            [p for p in debate.participants if p.side == ParticipantSide.CON and p.is_active],
            key=lambda p: p.side_order
        )
        
        turn_order = []
        sequence = 0
        
        # OPENING: All debaters give opening statements
        # Pro goes first, then Con (alternating by side_order)
        max_opening = max(len(pro_debaters), len(con_debaters))
        for i in range(max_opening):
            if i < len(pro_debaters):
                sequence += 1
                turn_order.append({
                    "sequence_number": sequence,
                    "phase": DebateStatus.OPENING,
                    "participant_id": pro_debaters[i].id,
                    "side": ParticipantSide.PRO,
                    "status": "pending"
                })
            if i < len(con_debaters):
                sequence += 1
                turn_order.append({
                    "sequence_number": sequence,
                    "phase": DebateStatus.OPENING,
                    "participant_id": con_debaters[i].id,
                    "side": ParticipantSide.CON,
                    "status": "pending"
                })
        
        # REBUTTALS: Alternating sides, each debater responds
        for round_num in range(1, debate.rebuttal_rounds + 1):
            phase = DebateStatus.REBUTTAL_1 if round_num == 1 else DebateStatus.REBUTTAL_2
            # Alternate which side starts each round
            sides_in_order = [ParticipantSide.CON, ParticipantSide.PRO] if round_num % 2 == 1 else [ParticipantSide.PRO, ParticipantSide.CON]
            
            for side in sides_in_order:
                debaters = pro_debaters if side == ParticipantSide.PRO else con_debaters
                for debater in debaters:
                    sequence += 1
                    turn_order.append({
                        "sequence_number": sequence,
                        "phase": phase,
                        "participant_id": debater.id,
                        "side": side,
                        "status": "pending"
                    })
        
        # CROSS EXAMINATION (optional)
        if debate.enable_cross_exam:
            for side in [ParticipantSide.PRO, ParticipantSide.CON]:
                debaters = pro_debaters if side == ParticipantSide.PRO else con_debaters
                for debater in debaters:
                    sequence += 1
                    turn_order.append({
                        "sequence_number": sequence,
                        "phase": DebateStatus.CROSS_EXAM,
                        "participant_id": debater.id,
                        "side": side,
                        "status": "pending"
                    })
        
        # CLOSING: Final statements
        for side in [ParticipantSide.PRO, ParticipantSide.CON]:
            debaters = pro_debaters if side == ParticipantSide.PRO else con_debaters
            for debater in debaters:
                sequence += 1
                turn_order.append({
                    "sequence_number": sequence,
                    "phase": DebateStatus.CLOSING,
                    "participant_id": debater.id,
                    "side": side,
                    "status": "pending"
                })
        
        self._turn_order = turn_order
        return turn_order
    
    def get_current_turn(self) -> Optional[Dict[str, Any]]:
        """Get the current turn that needs to be taken."""
        debate = self._get_debate()
        
        if not self._turn_order:
            self.build_turn_order()
        
        # Find first pending turn in current phase
        for turn in self._turn_order:
            if turn["phase"] == debate.current_phase and turn["status"] == "pending":
                return turn
        
        return None
    
    def can_submit_turn(self, participant_id: str) -> Tuple[bool, Optional[str]]:
        """Check if participant can submit a turn right now."""
        debate = self._get_debate()
        
        # Check debate status
        if debate.status not in [
            DebateStatus.OPENING, DebateStatus.REBUTTAL_1, 
            DebateStatus.REBUTTAL_2, DebateStatus.CROSS_EXAM, 
            DebateStatus.CLOSING
        ]:
            return False, f"Debate is in {debate.status.value} phase, cannot submit turns"
        
        # Get current turn
        current = self.get_current_turn()
        if not current:
            return False, "No pending turns in current phase"
        
        # Check if it's this participant's turn
        if current["participant_id"] != participant_id:
            return False, f"Not your turn. Current turn is for participant {current['participant_id']}"
        
        # Check phase deadline
        if debate.phase_deadline and datetime.utcnow() > debate.phase_deadline:
            return False, "Phase deadline has passed"
        
        return True, None
    
    def submit_turn(self, participant_id: str, content: str, 
                    time_taken_seconds: Optional[int] = None) -> Turn:
        """
        Submit a turn for the current participant.
        
        Raises InvalidTurnError if validation fails.
        """
        debate = self._get_debate()
        
        # Validate turn can be submitted
        can_submit, error = self.can_submit_turn(participant_id)
        if not can_submit:
            raise InvalidTurnError(error)
        
        # Get current turn info
        current = self.get_current_turn()
        
        # Validate content length (Unicode characters, not bytes)
        char_count = len(content)
        char_limit = debate.max_turn_length
        char_violation = char_count > char_limit
        
        # Calculate time taken
        if time_taken_seconds is None and debate.started_at:
            time_taken_seconds = int((datetime.utcnow() - debate.started_at).total_seconds())
        
        # Create turn
        turn = Turn(
            debate_id=self.debate_id,
            participant_id=participant_id,
            sequence_number=current["sequence_number"],
            phase=debate.current_phase,
            content=content,
            content_length=char_count,
            time_taken_seconds=time_taken_seconds,
            char_limit_violation=char_violation,
        )
        
        self.db.add(turn)
        
        # Update turn order status
        for t in self._turn_order:
            if t["sequence_number"] == current["sequence_number"]:
                t["status"] = "completed"
                break
        
        # Audit log
        self._audit_log(
            "turn_submitted",
            {
                "participant_id": participant_id,
                "sequence_number": current["sequence_number"],
                "phase": debate.current_phase.value,
                "char_count": char_count,
                "char_limit_violation": char_violation,
            },
            actor_type="agent",
            actor_id=participant_id
        )
        
        self.db.commit()
        self.db.refresh(turn)
        
        # Check if phase is complete
        self._check_phase_completion()
        
        return turn
    
    def _check_phase_completion(self) -> bool:
        """Check if current phase is complete and advance if needed."""
        debate = self._get_debate()
        
        # Count pending turns in current phase
        pending_in_phase = sum(
            1 for t in self._turn_order 
            if t["phase"] == debate.current_phase and t["status"] == "pending"
        )
        
        if pending_in_phase == 0:
            # Phase is complete, advance
            self._advance_phase()
            return True
        
        return False
    
    def _advance_phase(self):
        """Advance to the next phase of the debate."""
        debate = self._get_debate()
        current = debate.current_phase
        
        # Determine next phase
        transitions = self.VALID_TRANSITIONS.get(current, [])
        
        if current == DebateStatus.OPENING:
            next_phase = DebateStatus.REBUTTAL_1
        elif current == DebateStatus.REBUTTAL_1 and debate.rebuttal_rounds >= 2:
            next_phase = DebateStatus.REBUTTAL_2
        elif current == DebateStatus.REBUTTAL_2 and debate.enable_cross_exam:
            next_phase = DebateStatus.CROSS_EXAM
        elif current in [DebateStatus.REBUTTAL_1, DebateStatus.REBUTTAL_2, DebateStatus.CROSS_EXAM]:
            next_phase = DebateStatus.CLOSING
        elif current == DebateStatus.CLOSING:
            next_phase = DebateStatus.JUDGING
        elif current == DebateStatus.JUDGING:
            next_phase = DebateStatus.COMPLETE
            debate.ended_at = datetime.utcnow()
        else:
            raise StateTransitionError(f"Cannot advance from phase {current}")
        
        # Validate transition
        if next_phase not in transitions:
            raise StateTransitionError(f"Invalid transition from {current} to {next_phase}")
        
        # Update debate
        old_phase = debate.current_phase
        debate.current_phase = next_phase
        debate.status = next_phase
        
        # Set phase deadline
        duration = self.DEFAULT_PHASE_DURATIONS.get(next_phase, 600)
        debate.phase_deadline = datetime.utcnow() + timedelta(seconds=duration)
        
        # Audit log
        self._audit_log(
            "phase_advanced",
            {
                "from_phase": old_phase.value,
                "to_phase": next_phase.value,
                "deadline": debate.phase_deadline.isoformat() if debate.phase_deadline else None,
            }
        )
        
        self.db.commit()
    
    def start_debate(self) -> Debate:
        """Start the debate from PENDING state."""
        debate = self._get_debate()
        
        if debate.status != DebateStatus.PENDING:
            raise StateTransitionError(f"Cannot start debate from {debate.status}")
        
        # Build turn order
        self.build_turn_order()
        
        # BLOCKER FIX #4: Validate minimum roster requirements
        pro_count = len(self.get_participants_by_side(ParticipantSide.PRO))
        con_count = len(self.get_participants_by_side(ParticipantSide.CON))
        judge_count = len(self.get_participants_by_side(ParticipantSide.JUDGE))
        
        if pro_count < 1:
            raise StateTransitionError("Need at least 1 PRO participant")
        if con_count < 1:
            raise StateTransitionError("Need at least 1 CON participant")
        if judge_count < 1:
            raise StateTransitionError("Need at least 1 JUDGE to score the debate")
        
        # Advance to opening
        debate.status = DebateStatus.OPENING
        debate.current_phase = DebateStatus.OPENING
        debate.started_at = datetime.utcnow()
        debate.phase_deadline = datetime.utcnow() + timedelta(seconds=self.DEFAULT_PHASE_DURATIONS[DebateStatus.OPENING])
        
        self._audit_log("debate_started", {"participant_count": pro_count + con_count})
        
        self.db.commit()
        self.db.refresh(debate)
        return debate
    
    def cancel_debate(self, reason: Optional[str] = None) -> Debate:
        """Cancel the debate."""
        debate = self._get_debate()
        
        if debate.status in [DebateStatus.COMPLETE, DebateStatus.CANCELLED]:
            raise StateTransitionError(f"Cannot cancel debate in {debate.status}")
        
        debate.status = DebateStatus.CANCELLED
        debate.current_phase = DebateStatus.CANCELLED
        debate.ended_at = datetime.utcnow()
        
        self._audit_log("debate_cancelled", {"reason": reason})
        
        self.db.commit()
        self.db.refresh(debate)
        return debate
    
    def get_debate_state(self) -> Dict[str, Any]:
        """Get current debate state for realtime updates."""
        debate = self._get_debate()
        
        if not self._turn_order:
            self.build_turn_order()
        
        current_turn = self.get_current_turn()
        
        # Get participant info for turn order
        participant_map = {p.id: p for p in debate.participants}
        
        turn_order_display = []
        for t in self._turn_order:
            p = participant_map.get(t["participant_id"])
            turn_order_display.append({
                "participant_id": t["participant_id"],
                "participant_name": p.name if p else "Unknown",
                "side": t["side"].value,
                "sequence_number": t["sequence_number"],
                "phase": t["phase"].value,
                "status": t["status"]
            })
        
        # Get recent turns
        recent_turns = [
            {
                "id": t.id,
                "participant_id": t.participant_id,
                "participant_name": participant_map.get(t.participant_id, Participant(name="Unknown")).name,
                "side": participant_map.get(t.participant_id, Participant(side=ParticipantSide.OBSERVER)).side.value,
                "sequence_number": t.sequence_number,
                "phase": t.phase.value,
                "content_preview": t.content[:200] + "..." if len(t.content) > 200 else t.content,
                "submitted_at": t.submitted_at.isoformat(),
            }
            for t in debate.turns[-10:]  # Last 10 turns
        ]
        
        return {
            "debate_id": debate.id,
            "status": debate.status.value,
            "current_phase": debate.current_phase.value,
            "current_turn": {
                "participant_id": current_turn["participant_id"],
                "participant_name": participant_map.get(current_turn["participant_id"], Participant(name="Unknown")).name,
                "side": current_turn["side"].value,
                "sequence_number": current_turn["sequence_number"],
                "phase": current_turn["phase"].value,
            } if current_turn else None,
            "turn_order": turn_order_display,
            "phase_deadline": debate.phase_deadline.isoformat() if debate.phase_deadline else None,
            "recent_turns": recent_turns,
        }


class TurnTimeoutHandler:
    """Handle turn timeouts and auto-advance with retry logic."""
    
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 0.1  # Base delay in seconds
    
    def __init__(self, db: Optional[Session] = None):
        self.db = db or get_db_session()
    
    def _process_single_timeout_with_retry(self, debate: Debate) -> Optional[Dict[str, Any]]:
        """Process timeout for a single debate with retry on DB lock."""
        last_error = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                return self._process_single_timeout(debate)
            except Exception as e:
                last_error = e
                if "database is locked" in str(e).lower() or "lock" in str(e).lower():
                    import time
                    delay = self.RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
                    time.sleep(delay)
                    # Refresh the db session
                    self.db.rollback()
                    continue
                else:
                    raise
        
        # All retries exhausted
        print(f"Warning: Failed to process timeout for debate {debate.id} after {self.MAX_RETRIES} attempts: {last_error}")
        return None
    
    def _process_single_timeout(self, debate: Debate) -> Optional[Dict[str, Any]]:
        """Process timeout for a single debate."""
        sm = DebateStateMachine(debate.id, self.db)
        
        # Mark current turn as timeout
        current = sm.get_current_turn()
        if current:
            # Create timeout turn entry
            timeout_turn = Turn(
                debate_id=debate.id,
                participant_id=current["participant_id"],
                sequence_number=current["sequence_number"],
                phase=debate.current_phase,
                content="[TIMEOUT - No response within time limit]",
                content_length=0,
                was_timeout=True,
            )
            self.db.add(timeout_turn)
            
            # Mark as completed in turn order
            for t in sm._turn_order:
                if t["sequence_number"] == current["sequence_number"]:
                    t["status"] = "completed"
                    break
            
            results = {
                "debate_id": debate.id,
                "participant_id": current["participant_id"],
                "sequence_number": current["sequence_number"],
            }
            
            # Check if phase can advance
            sm._check_phase_completion()
            
            return results
        
        return None
    
    def process_timeouts(self) -> List[Dict[str, Any]]:
        """Process all timed-out debates and return affected debates."""
        now = datetime.utcnow()
        
        # Find debates with expired phase deadlines
        expired_debates = self.db.query(Debate).filter(
            and_(
                Debate.phase_deadline < now,
                Debate.status.in_([
                    DebateStatus.OPENING, DebateStatus.REBUTTAL_1,
                    DebateStatus.REBUTTAL_2, DebateStatus.CROSS_EXAM,
                    DebateStatus.CLOSING
                ])
            )
        ).all()
        
        results = []
        for debate in expired_debates:
            result = self._process_single_timeout_with_retry(debate)
            if result:
                results.append(result)
        
        self.db.commit()
        return results
