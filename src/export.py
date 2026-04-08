"""Export debates in various formats."""

import json
import csv
import io
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models import Debate, Participant, Turn, Score, ParticipantSide
from src.judging import JudgingEngine
from src.database import get_db_session


class DebateExporter:
    """Export debate data in multiple formats."""
    
    def __init__(self, db: Optional[Session] = None):
        self.db = db or get_db_session()
    
    def to_json(
        self, 
        debate_id: str, 
        include_scores: bool = True, 
        include_turns: bool = True
    ) -> str:
        """Export debate as JSON."""
        debate = self.db.query(Debate).filter(Debate.id == debate_id).first()
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        data = {
            "debate": {
                "id": debate.id,
                "title": debate.title,
                "proposition": debate.proposition,
                "description": debate.description,
                "status": debate.status.value,
                "created_at": debate.created_at.isoformat() if debate.created_at else None,
                "started_at": debate.started_at.isoformat() if debate.started_at else None,
                "ended_at": debate.ended_at.isoformat() if debate.ended_at else None,
                "winner": debate.winner_side.value if debate.winner_side else None,
                "confidence_score": debate.confidence_score,
            },
            "participants": [
                {
                    "id": p.id,
                    "name": p.name,
                    "side": p.side.value,
                    "type": p.participant_type.value,
                    "joined_at": p.joined_at.isoformat() if p.joined_at else None,
                }
                for p in debate.participants
            ],
        }
        
        if include_turns:
            data["turns"] = [
                {
                    "id": t.id,
                    "sequence_number": t.sequence_number,
                    "phase": t.phase.value,
                    "participant_id": t.participant_id,
                    "participant_name": self._get_participant_name(t.participant_id),
                    "content": t.content,
                    "content_length": t.content_length,
                    "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None,
                    "time_taken_seconds": t.time_taken_seconds,
                    "was_timeout": t.was_timeout,
                }
                for t in debate.turns
            ]
        
        if include_scores and debate.status.value == "complete":
            try:
                engine = JudgingEngine(debate_id, self.db)
                results = engine.calculate_results()
                data["results"] = results
            except Exception:
                data["results"] = None
        
        return json.dumps(data, indent=2)
    
    def to_markdown(
        self, 
        debate_id: str, 
        include_scores: bool = True, 
        include_turns: bool = True
    ) -> str:
        """Export debate as Markdown document."""
        debate = self.db.query(Debate).filter(Debate.id == debate_id).first()
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        lines = []
        
        # Header
        lines.append(f"# {debate.title}")
        lines.append("")
        lines.append(f"**Proposition:** {debate.proposition}")
        lines.append("")
        
        if debate.description:
            lines.append(debate.description)
            lines.append("")
        
        # Status
        lines.append(f"**Status:** {debate.status.value.upper()}")
        if debate.winner_side:
            lines.append(f"**Winner:** {debate.winner_side.value.upper()}")
        if debate.confidence_score is not None:
            lines.append(f"**Confidence:** {debate.confidence_score * 100:.0f}%")
        lines.append("")
        
        # Participants
        lines.append("## Participants")
        lines.append("")
        
        for side in [ParticipantSide.PRO, ParticipantSide.CON, ParticipantSide.JUDGE]:
            side_participants = [p for p in debate.participants if p.side == side]
            if side_participants:
                lines.append(f"### {side.value.upper()} ({len(side_participants)})")
                for p in side_participants:
                    lines.append(f"- **{p.name}** ({p.participant_type.value})")
                lines.append("")
        
        # Turns
        if include_turns and debate.turns:
            lines.append("## Debate Transcript")
            lines.append("")
            
            current_phase = None
            for turn in debate.turns:
                # Phase header
                if turn.phase.value != current_phase:
                    current_phase = turn.phase.value
                    lines.append(f"### {current_phase.upper().replace('_', ' ')}")
                    lines.append("")
                
                participant = self._get_participant(turn.participant_id)
                side_label = participant.side.value.upper() if participant else "?"
                
                lines.append(f"**{participant.name}** ({side_label}) — *{turn.submitted_at.strftime('%H:%M:%S') if turn.submitted_at else '?'}*")
                lines.append("")
                
                if turn.was_timeout:
                    lines.append("*[TIMEOUT — No response]*")
                else:
                    lines.append(turn.content)
                
                lines.append("")
        
        # Results
        if include_scores and debate.status.value == "complete":
            lines.append("## Results")
            lines.append("")
            
            try:
                engine = JudgingEngine(debate_id, self.db)
                results = engine.calculate_results()
                
                lines.append(results["rationale"])
                lines.append("")
                
                # Score table
                lines.append("### Individual Scores")
                lines.append("")
                lines.append("| Participant | Side | Score | Judges |")
                lines.append("|-------------|------|-------|--------|")
                
                for scorer in results["individual_scores"]:
                    lines.append(
                        f"| {scorer['name']} | {scorer['side'].upper()} | "
                        f"{scorer['scores']['weighted']:.2f}/10 | {scorer['judge_count']} |"
                    )
                
                lines.append("")
                
            except Exception as e:
                lines.append(f"*Error calculating results: {e}*")
                lines.append("")
        
        # Footer
        lines.append("---")
        lines.append("")
        lines.append(f"*Exported from Agent Debate System on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*")
        
        return "\n".join(lines)
    
    def to_csv(self, debate_id: str) -> str:
        """Export turns as CSV."""
        debate = self.db.query(Debate).filter(Debate.id == debate_id).first()
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "sequence", "phase", "participant_id", "participant_name", 
            "side", "content_length", "time_taken_seconds", 
            "was_timeout", "submitted_at"
        ])
        
        # Data
        for turn in debate.turns:
            participant = self._get_participant(turn.participant_id)
            writer.writerow([
                turn.sequence_number,
                turn.phase.value,
                turn.participant_id,
                participant.name if participant else "Unknown",
                participant.side.value if participant else "unknown",
                turn.content_length,
                turn.time_taken_seconds,
                turn.was_timeout,
                turn.submitted_at.isoformat() if turn.submitted_at else "",
            ])
        
        return output.getvalue()
    
    def _get_participant(self, participant_id: str) -> Optional[Participant]:
        """Get participant by ID."""
        return self.db.query(Participant).filter(Participant.id == participant_id).first()
    
    def _get_participant_name(self, participant_id: str) -> str:
        """Get participant name by ID."""
        p = self._get_participant(participant_id)
        return p.name if p else "Unknown"
