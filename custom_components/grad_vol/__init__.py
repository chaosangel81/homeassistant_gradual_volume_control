DOMAIN = "grad_vol"
import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass, config):
    """Set up is called when Home Assistant is loading our component."""
    volume_tasks = {}
    _LOGGER.debug("Setting up Gradual Volume component")

    def _normalize_entity_ids(call):
        raw = call.data.get('entity_id', [])
        if isinstance(raw, str):
            return [raw]
        return list(raw)

    async def async_handle_set_volume(call):
        """Handle the service call for gradually setting volume."""
        _LOGGER.debug("Gradual Volume service called")
        _LOGGER.debug(f"Service data: {call.data}")

        entity_ids = _normalize_entity_ids(call)
        target_volume = round(float(call.data.get('volume', 0)), 2)
        span = call.data.get('duration', 5)
        tasks = {}
        se = asyncio.Event()
        for entity_id in entity_ids:
            if entity_id in volume_tasks:
                volume_tasks[entity_id].cancel()
            tasks[entity_id] = hass.async_create_task(async_adjust_volume(entity_id, target_volume, span, se))
        _LOGGER.debug(f"Tasks: {tasks}")
        volume_tasks.update(tasks)
        _LOGGER.debug(f"Volume tasks: {volume_tasks}")
        _LOGGER.debug("starting tasks with start_event")
        se.set()  # Start all tasks at once
        await asyncio.gather(*tasks.values())
        _LOGGER.debug("Service_call finished")

    def _get_step(entity_id):
        step = 0.01
        state = hass.states.get(entity_id)
        if state and state.domain == 'number':
            step = state.attributes.get('step', 0.5)
        return step

    def _round_to_step(value, step):
        return round(round(value / step) * step, 2)

    async def async_adjust_volume(entity_id, target_volume, span, start_event):
        """Gradually adjust volume of an entity.

        Supports media_player (0-1 volume_level) and number (raw value, e.g. dB) entities.
        """
        _LOGGER.debug("Waiting for start signal...")
        await start_event.wait()
        _LOGGER.debug(f"Start signal received.")
        try:
            state = hass.states.get(entity_id)
            if not state or state.state in ('off', 'unavailable', 'unknown'):
                _LOGGER.debug(f"Entity {entity_id} is {state.state if state else 'not found'}, skipping volume adjustment.")
                return

            if state.domain == 'number':
                current = float(state.state)
                step = _get_step(entity_id)
                target = _round_to_step(float(target_volume), step)
                diff = abs(target - current)
                steps = max(int(diff / step), 1)
                sleeptime = span / steps
                _LOGGER.debug(f"Gradually adjusting {entity_id} from {current} to {target} in {steps} steps of {step} over {span}s.")

                while abs(target - current) >= step * 0.5:
                    if entity_id not in volume_tasks:
                        break
                    if target < current:
                        current = _round_to_step(current - step, step)
                    else:
                        current = _round_to_step(current + step, step)
                    if abs(current - target) < 0.001:
                        current = target
                    await hass.services.async_call('number', 'set_value', {
                        'entity_id': entity_id, 'value': current
                    })
                    await asyncio.sleep(sleeptime)

                _LOGGER.debug(f"Final {entity_id} set to {target}.")
                await hass.services.async_call('number', 'set_value', {
                    'entity_id': entity_id, 'value': target
                })
            else:
                current = state.attributes.get('volume_level')
                if current is None:
                    _LOGGER.debug(f"Volume level not found for {entity_id}, skipping volume adjustment.")
                    return

                current = round(float(current), 2)
                steps = abs(int((current - target_volume) / 0.01))
                sleeptime = span / max(steps, 1)
                _LOGGER.debug(f"Gradually adjusting {entity_id} from {current} to {target_volume} in {steps} steps over {span}s.")

                while abs(current - target_volume) >= 0.02:
                    if entity_id not in volume_tasks:
                        break
                    if target_volume < current:
                        current -= 0.01
                    else:
                        current += 0.01
                    await hass.services.async_call('media_player', 'volume_set', {
                        'entity_id': entity_id, 'volume_level': current
                    })
                    await asyncio.sleep(sleeptime)

                _LOGGER.debug(f"Final {entity_id} set to {target_volume}.")
                await hass.services.async_call('media_player', 'volume_set', {
                    'entity_id': entity_id, 'volume_level': target_volume
                })
            _LOGGER.debug("finished")

        except asyncio.CancelledError:
            _LOGGER.debug(f"Volume adjustment for {entity_id} was cancelled.")
        finally:
            volume_tasks.pop(entity_id, None)
            _LOGGER.debug(f"Volume task for {entity_id} removed from tasks.")

    async def async_cancel(call):
        """Cancel the volume adjustment for a specific entity or all."""
        entity_ids = _normalize_entity_ids(call)
        if not entity_ids:
            for task in volume_tasks.values():
                task.cancel()
            volume_tasks.clear()
        else:
            for entity_id in entity_ids:
                if entity_id in volume_tasks:
                    volume_tasks[entity_id].cancel()
                    volume_tasks.pop(entity_id, None)

    hass.services.async_register(DOMAIN, "set_volume", async_handle_set_volume)
    hass.services.async_register(DOMAIN, "cancel_all", async_cancel)
    
    return True
