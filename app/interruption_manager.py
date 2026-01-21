"""
Interruption Manager - tracks valid response sequences and handles barge-in
"""

class InterruptionManager:
    def __init__(self):
        self.current_sequence_id = 0
        self.active_sequences = set()
        self.is_agent_speaking = False
        
    def start_response(self) -> int:
        """Start a new agent response - returns sequence ID"""
        self.current_sequence_id += 1
        self.active_sequences.add(self.current_sequence_id)
        self.is_agent_speaking = True
        print(f"[interrupt] Starting response sequence_id={self.current_sequence_id}")
        return self.current_sequence_id
    
    def interrupt(self):
        """User interrupted - invalidate all active sequences"""
        if self.active_sequences:
            print(f"[interrupt] User interrupted! Invalidating {len(self.active_sequences)} sequences")
            self.active_sequences.clear()
            self.is_agent_speaking = False
        
    def is_valid(self, sequence_id: int) -> bool:
        """Check if this sequence should still continue"""
        return sequence_id in self.active_sequences
    
    def finish_response(self, sequence_id: int):
        """Mark response as complete"""
        if sequence_id in self.active_sequences:
            self.active_sequences.discard(sequence_id)
            if not self.active_sequences:
                self.is_agent_speaking = False
                print(f"[interrupt] Response complete sequence_id={sequence_id}")
