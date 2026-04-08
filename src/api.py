"""FastAPI endpoints for Agent Debate system."""

import hashlib
import secrets
import json
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

# Server start time (set during lifespan)
_server_start_time: float = 0.0

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from pydantic import ValidationError

from src.database import init_db, get_db_session, get_db
from src.models import (
    Debate, Participant, Turn, Score, InviteToken, AuditLog,
    DebateStatus, ParticipantSide, ParticipantType, InviteTokenStatus
)
from src.schemas import (
    DebateCreate, DebateUpdate, DebateResponse, DebateListResponse,
    ParticipantCreate, ParticipantResponse,
    TurnCreate, TurnSubmit, TurnResponse,
    ScoreCreate, ScoreResponse,
    InviteTokenCreate, InviteTokenResponse,
    JoinDebateRequest, JoinDebateResponse,
    DebateStateUpdate, WebSocketMessage,
    DebateExportRequest, DebateExportResponse, ExportFormat,
    DebateResultsResponse
)
from src.state_machine import DebateStateMachine, InvalidTurnError, StateTransitionError
from src.judging import JudgingEngine
from src.invite_tokens import InviteTokenManager


# ============== Connection Manager for WebSocket ==============

class ConnectionManager:
    """Manage WebSocket connections for realtime updates."""
    
    def __init__(self):
        # debate_id -> list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, debate_id: str):
        await websocket.accept()
        if debate_id not in self.active_connections:
            self.active_connections[debate_id] = []
        self.active_connections[debate_id].append(websocket)
    
    def disconnect(self, websocket: WebSocket, debate_id: str):
        if debate_id in self.active_connections:
            if websocket in self.active_connections[debate_id]:
                self.active_connections[debate_id].remove(websocket)
            if not self.active_connections[debate_id]:
                del self.active_connections[debate_id]
    
    async def broadcast(self, debate_id: str, message: Dict[str, Any]):
        """Broadcast message to all connections for a debate."""
        if debate_id not in self.active_connections:
            return
        
        disconnected = []
        for connection in self.active_connections[debate_id]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        # Clean up disconnected
        for conn in disconnected:
            self.disconnect(conn, debate_id)


manager = ConnectionManager()


# ============== FastAPI App ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup and track server start time."""
    global _server_start_time
    init_db()
    _server_start_time = time.time()
    yield


app = FastAPI(
    title="Agent Debate System",
    description="Controlled multi-agent debate platform",
    version="1.0.0",
    lifespan=lifespan
)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="static/templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== Debate Endpoints ==============

@app.post("/debates", response_model=DebateResponse, status_code=201)
def create_debate(debate: DebateCreate, db: Session = Depends(get_db)):
    """Create a new debate."""
    db_debate = Debate(
        title=debate.title,
        proposition=debate.proposition,
        description=debate.description,
        max_turn_length=debate.max_turn_length,
        max_turn_time_seconds=debate.max_turn_time_seconds,
        rebuttal_rounds=debate.rebuttal_rounds,
        enable_cross_exam=debate.enable_cross_exam,
        is_public=debate.is_public,
        created_by=debate.created_by,
    )
    
    db.add(db_debate)
    db.commit()
    db.refresh(db_debate)
    
    # Create initial participants if provided
    for p in debate.initial_participants or []:
        participant = Participant(
            debate_id=db_debate.id,
            name=p.name,
            participant_type=p.participant_type,
            side=p.side,
            side_order=p.side_order,
            agent_provider=p.agent_provider,
        )
        db.add(participant)
    
    db.commit()
    db.refresh(db_debate)
    
    return db_debate


@app.get("/debates", response_model=List[DebateListResponse])
def list_debates(
    status: Optional[DebateStatus] = None,
    is_public: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List debates with optional filtering."""
    query = db.query(Debate)
    
    if status:
        query = query.filter(Debate.status == status)
    if is_public is not None:
        query = query.filter(Debate.is_public == is_public)
    
    debates = query.order_by(Debate.created_at.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": d.id,
            "title": d.title,
            "proposition": d.proposition[:100] + "..." if len(d.proposition) > 100 else d.proposition,
            "status": d.status,
            "created_at": d.created_at,
            "participant_count": len(d.participants),
            "turn_count": len(d.turns),
            "is_public": d.is_public,
        }
        for d in debates
    ]


@app.get("/debates/{debate_id}", response_model=DebateResponse)
def get_debate(debate_id: str, db: Session = Depends(get_db)):
    """Get a specific debate by ID."""
    debate = db.query(Debate).options(
        joinedload(Debate.participants),
        joinedload(Debate.turns)
    ).filter(Debate.id == debate_id).first()
    
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    return debate


@app.patch("/debates/{debate_id}", response_model=DebateResponse)
def update_debate(debate_id: str, update: DebateUpdate, db: Session = Depends(get_db)):
    """Update debate metadata."""
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    if update.title:
        debate.title = update.title
    if update.description is not None:
        debate.description = update.description
    if update.status:
        debate.status = update.status
    
    db.commit()
    db.refresh(debate)
    return debate


@app.post("/debates/{debate_id}/start", response_model=DebateResponse)
def start_debate(
    debate_id: str, 
    host_id: str,  # BLOCKER FIX #1: Host-only guard
    db: Session = Depends(get_db)
):
    """Start a debate from PENDING state. Only the host can start."""
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    # BLOCKER FIX #1: Verify host-only authorization
    if debate.created_by != host_id:
        raise HTTPException(status_code=403, detail="Only the debate host can start the debate")
    
    sm = DebateStateMachine(debate_id, db)
    
    try:
        debate = sm.start_debate()
        
        # Broadcast state update
        import asyncio
        asyncio.create_task(manager.broadcast(debate_id, {
            "type": "debate_started",
            "data": sm.get_debate_state()
        }))
        
        return debate
    except StateTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/debates/{debate_id}/cancel", response_model=DebateResponse)
def cancel_debate(debate_id: str, reason: Optional[str] = None, db: Session = Depends(get_db)):
    """Cancel a debate."""
    sm = DebateStateMachine(debate_id, db)
    
    try:
        debate = sm.cancel_debate(reason)
        
        import asyncio
        asyncio.create_task(manager.broadcast(debate_id, {
            "type": "debate_cancelled",
            "data": {"reason": reason}
        }))
        
        return debate
    except StateTransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============== Turn Endpoints ==============

@app.post("/debates/{debate_id}/turns", response_model=TurnResponse, status_code=201)
def submit_turn(
    debate_id: str, 
    turn: TurnSubmit, 
    participant_id: str,
    db: Session = Depends(get_db)
):
    """Submit a turn for a participant."""
    sm = DebateStateMachine(debate_id, db)
    
    try:
        # Validate content length
        char_count = len(turn.content)
        debate = db.query(Debate).filter(Debate.id == debate_id).first()
        
        if char_count > debate.max_turn_length:
            raise HTTPException(
                status_code=400, 
                detail=f"Content exceeds maximum length ({char_count} > {debate.max_turn_length} characters)"
            )
        
        # Submit turn
        db_turn = sm.submit_turn(participant_id, turn.content)
        
        # Get fresh state
        state = sm.get_debate_state()
        
        # Broadcast update
        import asyncio
        asyncio.create_task(manager.broadcast(debate_id, {
            "type": "turn_submitted",
            "data": {
                "turn": {
                    "id": db_turn.id,
                    "participant_id": db_turn.participant_id,
                    "sequence_number": db_turn.sequence_number,
                    "phase": db_turn.phase.value,
                    "content_preview": db_turn.content[:200] + "..." if len(db_turn.content) > 200 else db_turn.content,
                },
                "state": state
            }
        }))
        
        # Build response
        participant = db.query(Participant).filter(Participant.id == participant_id).first()
        return {
            "id": db_turn.id,
            "debate_id": db_turn.debate_id,
            "participant_id": db_turn.participant_id,
            "participant_name": participant.name if participant else "Unknown",
            "participant_side": participant.side if participant else ParticipantSide.OBSERVER,
            "sequence_number": db_turn.sequence_number,
            "phase": db_turn.phase,
            "content": db_turn.content,
            "content_length": db_turn.content_length,
            "submitted_at": db_turn.submitted_at,
            "time_taken_seconds": db_turn.time_taken_seconds,
            "was_timeout": db_turn.was_timeout,
            "char_limit_violation": db_turn.char_limit_violation,
            "replies_to_turn_id": db_turn.replies_to_turn_id,
        }
        
    except InvalidTurnError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/debates/{debate_id}/turns", response_model=List[TurnResponse])
def list_turns(
    debate_id: str, 
    participant_id: Optional[str] = None,
    phase: Optional[DebateStatus] = None,
    db: Session = Depends(get_db)
):
    """List turns for a debate."""
    query = db.query(Turn).filter(Turn.debate_id == debate_id)
    
    if participant_id:
        query = query.filter(Turn.participant_id == participant_id)
    if phase:
        query = query.filter(Turn.phase == phase)
    
    turns = query.order_by(Turn.sequence_number).all()
    
    result = []
    for t in turns:
        participant = db.query(Participant).filter(Participant.id == t.participant_id).first()
        result.append({
            "id": t.id,
            "debate_id": t.debate_id,
            "participant_id": t.participant_id,
            "participant_name": participant.name if participant else "Unknown",
            "participant_side": participant.side if participant else ParticipantSide.OBSERVER,
            "sequence_number": t.sequence_number,
            "phase": t.phase,
            "content": t.content,
            "content_length": t.content_length,
            "submitted_at": t.submitted_at,
            "time_taken_seconds": t.time_taken_seconds,
            "was_timeout": t.was_timeout,
            "char_limit_violation": t.char_limit_violation,
            "replies_to_turn_id": t.replies_to_turn_id,
        })
    
    return result


# ============== Score/Judging Endpoints ==============

@app.post("/debates/{debate_id}/scores", response_model=ScoreResponse, status_code=201)
def submit_score(
    debate_id: str,
    score: ScoreCreate,
    judge_id: str,
    db: Session = Depends(get_db)
):
    """Submit a judge score for a participant."""
    # Validate judge
    judge = db.query(Participant).filter(
        Participant.id == judge_id,
        Participant.debate_id == debate_id,
        Participant.side == ParticipantSide.JUDGE
    ).first()
    
    if not judge:
        raise HTTPException(status_code=403, detail="Not a valid judge for this debate")
    
    # Validate participant
    participant = db.query(Participant).filter(
        Participant.id == score.participant_id,
        Participant.debate_id == debate_id
    ).first()
    
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    
    # Calculate scores
    total = (score.argument_quality + score.evidence_quality + 
             score.rebuttal_strength + score.clarity + score.compliance)
    weighted = total / 5  # Average
    
    # Create tamper-evident hash
    score_data = {
        "debate_id": debate_id,
        "participant_id": score.participant_id,
        "judge_id": judge_id,
        "argument_quality": score.argument_quality,
        "evidence_quality": score.evidence_quality,
        "rebuttal_strength": score.rebuttal_strength,
        "clarity": score.clarity,
        "compliance": score.compliance,
        "timestamp": datetime.utcnow().isoformat(),
    }
    score_hash = hashlib.sha256(json.dumps(score_data, sort_keys=True).encode()).hexdigest()
    
    db_score = Score(
        debate_id=debate_id,
        participant_id=score.participant_id,
        judge_id=judge_id,
        argument_quality=score.argument_quality,
        evidence_quality=score.evidence_quality,
        rebuttal_strength=score.rebuttal_strength,
        clarity=score.clarity,
        compliance=score.compliance,
        total_score=total,
        weighted_score=weighted,
        rationale=score.rationale,
        strengths=score.strengths,
        weaknesses=score.weaknesses,
        previous_hash=score_hash,
    )
    
    db.add(db_score)
    
    # BLOCKER FIX #3: Handle duplicate score attempts
    try:
        db.commit()
        db.refresh(db_score)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, 
            detail="Judge has already scored this participant. Use PATCH to update scores."
        )
    
    return {
        "id": db_score.id,
        "debate_id": db_score.debate_id,
        "participant_id": db_score.participant_id,
        "judge_id": db_score.judge_id,
        "judge_name": judge.name,
        "argument_quality": db_score.argument_quality,
        "evidence_quality": db_score.evidence_quality,
        "rebuttal_strength": db_score.rebuttal_strength,
        "clarity": db_score.clarity,
        "compliance": db_score.compliance,
        "total_score": db_score.total_score,
        "weighted_score": db_score.weighted_score,
        "rationale": db_score.rationale,
        "strengths": db_score.strengths,
        "weaknesses": db_score.weaknesses,
        "created_at": db_score.created_at,
        "version": db_score.version,
    }


@app.get("/debates/{debate_id}/scores", response_model=List[ScoreResponse])
def list_scores(debate_id: str, db: Session = Depends(get_db)):
    """List all scores for a debate."""
    scores = db.query(Score).filter(Score.debate_id == debate_id).all()
    
    result = []
    for s in scores:
        judge = db.query(Participant).filter(Participant.id == s.judge_id).first()
        result.append({
            "id": s.id,
            "debate_id": s.debate_id,
            "participant_id": s.participant_id,
            "judge_id": s.judge_id,
            "judge_name": judge.name if judge else "Unknown",
            "argument_quality": s.argument_quality,
            "evidence_quality": s.evidence_quality,
            "rebuttal_strength": s.rebuttal_strength,
            "clarity": s.clarity,
            "compliance": s.compliance,
            "total_score": s.total_score,
            "weighted_score": s.weighted_score,
            "rationale": s.rationale,
            "strengths": s.strengths,
            "weaknesses": s.weaknesses,
            "created_at": s.created_at,
            "version": s.version,
        })
    
    return result


@app.post("/debates/{debate_id}/finalize", response_model=DebateResponse)
def finalize_debate(
    debate_id: str, 
    host_id: str,  # BLOCKER FIX #1: Host-only authorization
    db: Session = Depends(get_db)
):
    """Finalize debate with judging results. Only host can finalize."""
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    # BLOCKER FIX #1: Verify host-only authorization
    if debate.created_by != host_id:
        raise HTTPException(status_code=403, detail="Only the debate host can finalize")
    
    # BLOCKER FIX #5: Validate judging completion before finalizing
    judges = db.query(Participant).filter(
        Participant.debate_id == debate_id,
        Participant.side == ParticipantSide.JUDGE
    ).all()
    
    debaters = db.query(Participant).filter(
        Participant.debate_id == debate_id,
        Participant.side.in_([ParticipantSide.PRO, ParticipantSide.CON])
    ).all()
    
    expected_scores = len(judges) * len(debaters)
    actual_scores = db.query(Score).filter(Score.debate_id == debate_id).count()
    
    if actual_scores < expected_scores:
        missing = expected_scores - actual_scores
        raise HTTPException(
            status_code=400, 
            detail=f"Judging incomplete: {missing} score(s) missing. Expected {expected_scores}, got {actual_scores}."
        )
    
    engine = JudgingEngine(debate_id, db)
    
    try:
        results = engine.calculate_results()
        
        debate.winner_side = ParticipantSide(results["winner"]) if results["winner"] else None
        debate.confidence_score = results["confidence"]
        debate.judge_rationale = results["rationale"]
        debate.status = DebateStatus.COMPLETE
        debate.current_phase = DebateStatus.COMPLETE
        debate.ended_at = datetime.utcnow()
        
        db.commit()
        db.refresh(debate)
        
        # Broadcast
        import asyncio
        asyncio.create_task(manager.broadcast(debate_id, {
            "type": "debate_finalized",
            "data": results
        }))
        
        return debate
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============== Results Endpoints ==============

@app.get("/debates/{debate_id}/results", response_model=DebateResultsResponse)
def get_results(debate_id: str, db: Session = Depends(get_db)):
    """Get complete debate results."""
    engine = JudgingEngine(debate_id, db)
    
    try:
        results = engine.calculate_results()
        debate = db.query(Debate).filter(Debate.id == debate_id).first()
        
        return {
            "debate": debate,
            "team_scores": results["team_scores"],
            "individual_scores": results["individual_scores"],
            "winner": results["winner"],
            "confidence": results["confidence"],
            "rationale": results["rationale"],
            "score_breakdown": results["score_breakdown"],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/debates/{debate_id}/export")
def export_debate(debate_id: str, request: DebateExportRequest, db: Session = Depends(get_db)):
    """Export debate in various formats."""
    from src.export import DebateExporter
    
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    exporter = DebateExporter(db)
    
    if request.format == ExportFormat.JSON:
        content = exporter.to_json(debate_id, request.include_scores, request.include_turns)
        content_type = "application/json"
        filename = f"debate_{debate_id}.json"
    elif request.format == ExportFormat.MARKDOWN:
        content = exporter.to_markdown(debate_id, request.include_scores, request.include_turns)
        content_type = "text/markdown"
        filename = f"debate_{debate_id}.md"
    elif request.format == ExportFormat.CSV:
        content = exporter.to_csv(debate_id)
        content_type = "text/csv"
        filename = f"debate_{debate_id}.csv"
    else:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    return PlainTextResponse(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============== Invite Token Endpoints ==============

@app.post("/debates/{debate_id}/invite-tokens", response_model=InviteTokenResponse, status_code=201)
def create_invite_token(
    debate_id: str,
    token_req: InviteTokenCreate,
    created_by: str,
    db: Session = Depends(get_db)
):
    """Create an invite token for a debate."""
    manager = InviteTokenManager(db)
    
    token, token_preview = manager.create_token(
        debate_id=debate_id,
        side=token_req.side,
        participant_type=token_req.participant_type,
        max_uses=token_req.max_uses,
        expires_hours=token_req.expires_hours,
        created_by=created_by,
    )
    
    # Get the created token record
    token_record = db.query(InviteToken).filter(InviteToken.token_preview == token_preview).first()
    
    return {
        "id": token_record.id,
        "debate_id": token_record.debate_id,
        "token": token,  # Only shown once on creation
        "token_preview": token_record.token_preview,
        "side": token_record.side,
        "participant_type": token_record.participant_type,
        "max_uses": token_record.max_uses,
        "used_count": token_record.used_count,
        "status": token_record.status,
        "expires_at": token_record.expires_at,
        "created_at": token_record.created_at,
    }


@app.get("/debates/{debate_id}/invite-tokens", response_model=List[InviteTokenResponse])
def list_invite_tokens(debate_id: str, db: Session = Depends(get_db)):
    """List invite tokens for a debate."""
    tokens = db.query(InviteToken).filter(InviteToken.debate_id == debate_id).all()
    
    return [
        {
            "id": t.id,
            "debate_id": t.debate_id,
            "token_preview": t.token_preview,
            "side": t.side,
            "participant_type": t.participant_type,
            "max_uses": t.max_uses,
            "used_count": t.used_count,
            "status": t.status,
            "expires_at": t.expires_at,
            "created_at": t.created_at,
        }
        for t in tokens
    ]


@app.post("/debates/join", response_model=JoinDebateResponse)
def join_debate(request: JoinDebateRequest, db: Session = Depends(get_db)):
    """Join a debate using an invite token."""
    manager = InviteTokenManager(db)
    
    try:
        participant = manager.use_token(
            token=request.token,
            participant_name=request.name,
            participant_type=request.participant_type,
        )
        
        # Broadcast
        import asyncio
        asyncio.create_task(manager.broadcast(participant.debate_id, {
            "type": "participant_joined",
            "data": {
                "participant_id": participant.id,
                "name": participant.name,
                "side": participant.side.value,
            }
        }))
        
        return {
            "success": True,
            "participant_id": participant.id,
            "debate_id": participant.debate_id,
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
        }


# ============== WebSocket Endpoint ==============

@app.websocket("/debates/{debate_id}/ws")
async def websocket_endpoint(websocket: WebSocket, debate_id: str):
    """WebSocket for realtime debate updates."""
    await manager.connect(websocket, debate_id)
    
    try:
        # Send initial state
        db = get_db_session()
        sm = DebateStateMachine(debate_id, db)
        state = sm.get_debate_state()
        await websocket.send_json({
            "type": "initial_state",
            "data": state
        })
        
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_json()
            
            # Handle ping
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
            # Handle state refresh request
            elif data.get("type") == "refresh":
                state = sm.get_debate_state()
                await websocket.send_json({
                    "type": "state_update",
                    "data": state
                })
                
    except WebSocketDisconnect:
        manager.disconnect(websocket, debate_id)
    except Exception as e:
        manager.disconnect(websocket, debate_id)


# ============== Health Check ==============

@app.get("/health")
def health_check():
    """M4.1: Enhanced health check with DB connectivity and uptime."""
    global _server_start_time
    db_status = "disconnected"
    try:
        db = SessionLocal()
        db.execute(db.text("SELECT 1"))
        db.close()
        db_status = "connected"
    except Exception:
        pass

    return {
        "status": "ok",
        "db": db_status,
        "uptime": round(time.time() - _server_start_time, 1),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    """Serve the landing page."""
    return templates.TemplateResponse("index.html", {"request": request})


# ============== HTML Template Routes ==============

@app.get("/debates/{debate_id}/view", response_class=HTMLResponse)
def view_debate(request: Request, debate_id: str, db: Session = Depends(get_db)):
    """Render the debate table UI."""
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    return templates.TemplateResponse("debate_table.html", {
        "request": request,
        "debate": debate
    })


@app.get("/debates/{debate_id}/results/view", response_class=HTMLResponse)
def view_results(request: Request, debate_id: str, db: Session = Depends(get_db)):
    """Render the results page."""
    from src.judging import JudgingEngine
    
    debate = db.query(Debate).filter(Debate.id == debate_id).first()
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    
    # Calculate results if debate is complete
    results = None
    if debate.status == DebateStatus.COMPLETE or debate.scores:
        try:
            engine = JudgingEngine(debate_id, db)
            results = engine.calculate_results()
        except Exception:
            results = None
    
    return templates.TemplateResponse("results.html", {
        "request": request,
        "debate": debate,
        "results": results or {"winner": None, "confidence": 0, "rationale": "No results available", "team_scores": {}, "individual_scores": []}
    })
