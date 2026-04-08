"""Demo script showing how to use the Agent Debate System."""

import requests
import json

BASE_URL = "http://localhost:8000"


def create_debate():
    """Create a sample debate."""
    response = requests.post(f"{BASE_URL}/debates", json={
        "title": "AI Safety: Should We Pause Giant AI Experiments?",
        "proposition": "We should pause giant AI experiments until we understand their risks better",
        "description": "A structured debate on AI safety and the proposed pause on large-scale AI training runs.",
        "created_by": "demo_user",
        "max_turn_length": 1500,
        "max_turn_time_seconds": 300,
        "rebuttal_rounds": 2,
        "is_public": True
    })
    
    if response.status_code == 201:
        debate = response.json()
        print(f"✓ Created debate: {debate['id']}")
        print(f"  Title: {debate['title']}")
        return debate['id']
    else:
        print(f"✗ Failed to create debate: {response.text}")
        return None


def create_invite_tokens(debate_id):
    """Create invite tokens for all sides."""
    tokens = {}
    
    # PRO token
    response = requests.post(
        f"{BASE_URL}/debates/{debate_id}/invite-tokens?created_by=demo_user",
        json={"side": "pro", "participant_type": "agent", "max_uses": 2}
    )
    if response.status_code == 201:
        tokens['pro'] = response.json()
        print(f"✓ Created PRO token: {tokens['pro']['token_preview']}...")
    
    # CON token
    response = requests.post(
        f"{BASE_URL}/debates/{debate_id}/invite-tokens?created_by=demo_user",
        json={"side": "con", "participant_type": "agent", "max_uses": 2}
    )
    if response.status_code == 201:
        tokens['con'] = response.json()
        print(f"✓ Created CON token: {tokens['con']['token_preview']}...")
    
    # Judge token
    response = requests.post(
        f"{BASE_URL}/debates/{debate_id}/invite-tokens?created_by=demo_user",
        json={"side": "judge", "participant_type": "human", "max_uses": 3}
    )
    if response.status_code == 201:
        tokens['judge'] = response.json()
        print(f"✓ Created JUDGE token: {tokens['judge']['token_preview']}...")
    
    return tokens


def join_debate(token, name, side):
    """Join a debate with an invite token."""
    response = requests.post(f"{BASE_URL}/debates/join", json={
        "token": token,
        "name": name,
        "participant_type": "agent"
    })
    
    if response.status_code == 200:
        result = response.json()
        if result.get('success'):
            print(f"✓ {name} joined as {side}")
            return result['participant_id']
        else:
            print(f"✗ {name} failed to join: {result.get('error')}")
    else:
        print(f"✗ {name} failed to join: {response.text}")
    
    return None


def start_debate(debate_id):
    """Start the debate."""
    response = requests.post(f"{BASE_URL}/debates/{debate_id}/start")
    
    if response.status_code == 200:
        debate = response.json()
        print(f"✓ Debate started! Phase: {debate['current_phase']}")
        return True
    else:
        print(f"✗ Failed to start debate: {response.text}")
        return False


def submit_turn(debate_id, participant_id, content):
    """Submit a turn."""
    response = requests.post(
        f"{BASE_URL}/debates/{debate_id}/turns?participant_id={participant_id}",
        json={"content": content}
    )
    
    if response.status_code == 200:
        turn = response.json()
        print(f"✓ Turn #{turn['sequence_number']} submitted")
        return turn
    else:
        print(f"✗ Failed to submit turn: {response.text}")
        return None


def submit_score(debate_id, judge_id, participant_id, scores):
    """Submit a judge score."""
    response = requests.post(
        f"{BASE_URL}/debates/{debate_id}/scores?judge_id={judge_id}",
        json={
            "participant_id": participant_id,
            **scores
        }
    )
    
    if response.status_code == 201:
        score = response.json()
        print(f"✓ Score submitted for {participant_id[:8]}...: {score['weighted_score']:.1f}/10")
        return score
    else:
        print(f"✗ Failed to submit score: {response.text}")
        return None


def finalize_debate(debate_id):
    """Finalize the debate and get results."""
    response = requests.post(f"{BASE_URL}/debates/{debate_id}/finalize")
    
    if response.status_code == 200:
        debate = response.json()
        print(f"✓ Debate finalized! Winner: {debate.get('winner_side', 'TIE')}")
        return debate
    else:
        print(f"✗ Failed to finalize: {response.text}")
        return None


def get_results(debate_id):
    """Get debate results."""
    response = requests.get(f"{BASE_URL}/debates/{debate_id}/results")
    
    if response.status_code == 200:
        results = response.json()
        print("\n" + "="*60)
        print("DEBATE RESULTS")
        print("="*60)
        print(f"Winner: {results.get('winner', 'TIE')}")
        print(f"Confidence: {results.get('confidence', 0)*100:.0f}%")
        print("\nRationale:")
        print(results.get('rationale', 'No rationale available'))
        return results
    else:
        print(f"✗ Failed to get results: {response.text}")
        return None


def main():
    """Run the demo."""
    print("Agent Debate System Demo")
    print("="*60)
    
    # Create debate
    debate_id = create_debate()
    if not debate_id:
        return
    
    # Create invite tokens
    tokens = create_invite_tokens(debate_id)
    
    # Join debate
    print("\n--- Joining Debate ---")
    participants = {}
    participants['pro1'] = join_debate(tokens['pro']['token'], "Agent Pro-Alpha", "PRO")
    participants['pro2'] = join_debate(tokens['pro']['token'], "Agent Pro-Beta", "PRO")
    participants['con1'] = join_debate(tokens['con']['token'], "Agent Con-Alpha", "CON")
    participants['con2'] = join_debate(tokens['con']['token'], "Agent Con-Beta", "CON")
    participants['judge1'] = join_debate(tokens['judge']['token'], "Judge One", "JUDGE")
    participants['judge2'] = join_debate(tokens['judge']['token'], "Judge Two", "JUDGE")
    
    # Start debate
    print("\n--- Starting Debate ---")
    if not start_debate(debate_id):
        return
    
    # Get debate state to see turn order
    print("\n--- Debate State ---")
    response = requests.get(f"{BASE_URL}/debates/{debate_id}")
    debate = response.json()
    print(f"Status: {debate['status']}")
    print(f"Current Phase: {debate['current_phase']}")
    print(f"Participants: {len(debate['participants'])}")
    
    print("\n--- Submitting Turns (Opening) ---")
    # Submit opening statements
    opening_statements = [
        (participants['pro1'], "AI systems are advancing faster than our ability to understand and control them. We need a pause to establish safety protocols before proceeding with experiments that could pose existential risks."),
        (participants['con1'], "Pausing AI research would cede technological leadership to authoritarian regimes. Innovation should continue with safety measures, not through blanket moratoriums that stifle progress."),
        (participants['pro2'], "The proposed pause is targeted at giant experiments - systems more powerful than GPT-4. This is a reasonable precaution given our lack of understanding of emergent capabilities in large models."),
        (participants['con2'], "History shows that regulation through pauses rarely works. Better to develop AI openly where safety research can be published, rather than drive development underground where oversight is impossible."),
    ]
    
    for pid, content in opening_statements:
        submit_turn(debate_id, pid, content)
    
    print("\n--- Submitting Turns (Rebuttal) ---")
    # Submit rebuttals
    rebuttals = [
        (participants['con1'], "The concern about authoritarian regimes is valid, but international cooperation on AI safety is possible. The Asilomar AI Principles show the field can self-regulate."),
        (participants['pro1'], "Self-regulation has failed in every industry. Without binding constraints, competitive pressures will always prioritize capabilities over safety."),
    ]
    
    for pid, content in rebuttals:
        submit_turn(debate_id, pid, content)
    
    print("\n--- Submitting Turns (Closing) ---")
    # Submit closing statements
    closing = [
        (participants['pro1'], "We must prioritize caution when the stakes are potentially existential. A targeted pause on the largest experiments is the responsible path forward."),
        (participants['con1'], "Progress and safety aren't mutually exclusive. We can develop AI responsibly without halting the research that promises to solve humanity's greatest challenges."),
    ]
    
    for pid, content in closing:
        submit_turn(debate_id, pid, content)
    
    print("\n--- Judge Scoring ---")
    # Submit scores from judges
    for judge_key in ['judge1', 'judge2']:
        judge_id = participants[judge_key]
        for participant_key, participant_id in participants.items():
            if participant_key.startswith('judge'):
                continue
            
            score = {
                "argument_quality": 7.5 if 'pro' in participant_key else 7.0,
                "evidence_quality": 7.0 if 'pro' in participant_key else 6.5,
                "rebuttal_strength": 8.0 if 'pro' in participant_key else 7.5,
                "clarity": 8.5 if 'pro' in participant_key else 8.0,
                "compliance": 10.0,
                "rationale": "Solid performance throughout the debate."
            }
            submit_score(debate_id, judge_id, participant_id, score)
    
    print("\n--- Finalizing Debate ---")
    finalize_debate(debate_id)
    
    # Get final results
    get_results(debate_id)
    
    print("\n" + "="*60)
    print(f"Demo complete! View the debate at: {BASE_URL}/debates/{debate_id}/view")
    print(f"Results page: {BASE_URL}/debates/{debate_id}/results/view")


if __name__ == "__main__":
    main()
