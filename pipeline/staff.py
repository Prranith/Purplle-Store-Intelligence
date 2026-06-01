def is_track_staff(track_history: list, zone_history: list) -> bool:
    """
    Evaluates whether a track is store staff based on counter duration and presence.
    """
    if not track_history:
        return False
        
    # Heuristic 1: If track is present at CASH COUNTER for more than 60% of the active duration
    cc_count = sum(1 for zone in zone_history if zone == "ZONE_CASH_COUNTER")
    total_count = len(zone_history)
    
    if total_count > 0 and (cc_count / total_count) >= 0.60:
        return True
        
    # Heuristic 2: Long duration presence (simulated via total frames tracked)
    # 5 frames per second * 60 seconds * 60 minutes * 3 hours = 54,000 frames
    if len(track_history) > 54000:
        return True
        
    return False
