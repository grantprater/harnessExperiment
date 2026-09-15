def live_mine_oak_log(controller: RawMotorController, **kwargs) -> dict:
    ticks = 0
    max_ticks = 100
    success = False

    # First verify if we are looking at an oak_log or need to find it via raycast
    # The prompt says: "Aim at the oak_log block in front of you. Check that a block is targeted using raycast_crosshair()."
    # Let's check the crosshair first
    pos, block, dist = controller.raycast_crosshair()
    
    # If not already looking directly at it, we can scan slightly or assume the user placed it in front.
    # Let's try to find an oak_log if the current crosshair is not hitting one, or just proceed if it is.
    # Actually, a simple approach: if block is None or block.name != 'oak_log', we can try searching nearby angles.
    # Let's do a quick scan if needed, or just start mining if it's there.
    if block is None or getattr(block, 'name', '') != 'oak_log':
        # Simple scan around center
        found = False
        for p_offset in [0, 5, -5, 10, -10]:
            for y_offset in [0, 10, -10]:
                controller.set_look(float(y_offset), float(p_offset))
                pos, block, dist = controller.raycast_crosshair()
                if block is not None and getattr(block, 'name', '') == 'oak_log':
                    found = True
                    break
            if found:
                break

    try:
        controller.mouse_down('left')
        while ticks < max_ticks:
            res = controller.tick(1)
            ticks += 1
            
            # Check if block broke
            broken_blocks = res.get('broken_blocks', [])
            if broken_blocks:
                success = True
                break
                
            # Alternatively check if raycast no longer hits an oak_log (meaning it's broken)
            pos, block, dist = controller.raycast_crosshair()
            if block is None or getattr(block, 'name', '') != 'oak_log':
                # Might have successfully broken it
                success = True
                break
    finally:
        controller.mouse_up('left')

    return {'success': success, 'ticks_elapsed': ticks}