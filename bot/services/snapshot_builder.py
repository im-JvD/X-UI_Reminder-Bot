"""
Service for building comprehensive data snapshots per panel.
"""
import logging
import time
from typing import Dict, List, Set

from ..api.client import PanelAPI
from ..database.repositories.panel_repository import PanelRepository
from ..database.repositories.reseller_repository import ResellerRepository
from ..config.settings import (
    SUPERADMINS,
    EXPIRING_SECONDS_THRESHOLD,
    EXPIRING_BYTES_THRESHOLD
)

logger = logging.getLogger(__name__)

def _calc_status_for_client(client: dict, now: float) -> tuple[bool, bool]:
    """Calculate if a client is expiring or expired."""
    try:
        up = int(client.get("up", 0) or 0)
        down = int(client.get("down", 0) or 0)
        used_bytes = up + down

        total_gb_val = client.get("totalGB", 0) or 0
        total_bytes_val = client.get("total", 0) or 0

        total_bytes = 0
        if float(total_gb_val or 0) > 0:
            total_bytes = int(float(total_gb_val) * (1024**3))
        elif float(total_bytes_val or 0) > 0:
            total_bytes = int(float(total_bytes_val))

        expiry_ms = int(
            client.get("expiryTime", 0) or
            client.get("expire", 0) or
            client.get("expiry", 0) or 0
        )

        left_bytes = None
        if total_bytes > 0:
            left_bytes = total_bytes - used_bytes

        expired_quota = (left_bytes is not None and left_bytes <= 0)
        expired_time = (expiry_ms > 0 and (expiry_ms / 1000.0) <= now)
        is_expired = expired_quota or expired_time

        is_expiring = False
        if not is_expired:
            if expiry_ms > 0:
                secs_left = (expiry_ms / 1000.0) - now
                if 0 < secs_left <= EXPIRING_SECONDS_THRESHOLD:
                    is_expiring = True

            if left_bytes is not None and total_bytes > 0:
                if 0 < left_bytes <= EXPIRING_BYTES_THRESHOLD:
                    is_expiring = True

        return is_expiring, is_expired

    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"Error calculating status for client: {e}")
        return False, False

def _extract_clients_from_inbound(inbound: dict) -> List[dict]:
    """Extract client data from an inbound configuration."""
    clients = []

    if not isinstance(inbound, dict):
        return clients

    if 'clientStats' in inbound and isinstance(inbound['clientStats'], list):
        clients = inbound['clientStats']
    elif 'settings' in inbound:
        try:
            if isinstance(inbound['settings'], str):
                import json
                settings = json.loads(inbound['settings'])
            else:
                settings = inbound['settings']

            if isinstance(settings, dict) and 'clients' in settings:
                clients = settings['clients']
        except:
            pass
    elif 'clients' in inbound and isinstance(inbound['clients'], list):
        clients = inbound['clients']

    return [c for c in clients if isinstance(c, dict)]

async def build_snapshot(telegram_id: int) -> Dict:
    """Build a comprehensive snapshot of user data per panel."""
    panels_snapshot = {}

    try:
        panel_repo = PanelRepository("data.db")
        reseller_repo = ResellerRepository("data.db")

        if telegram_id in SUPERADMINS:
            panels = await panel_repo.get_all_panels()
            scoped_inbounds = {panel[0]: None for panel in panels}
        else:
            scoped_inbounds = await reseller_repo.get_reseller_inbounds_by_panel(telegram_id)

        if not scoped_inbounds:
            logger.warning(f"User {telegram_id} has no panels or inbounds")
            return panels_snapshot

        now = time.time()

        for panel_id, assigned_inbound_ids in scoped_inbounds.items():
            try:
                panel_data = await panel_repo.get_panel_by_id(panel_id)
                if not panel_data:
                    logger.warning(f"Panel {panel_id} not found")
                    continue

                async with PanelAPI(
                    username=panel_data['username'],
                    password=panel_data['password'],
                    base_url=panel_data['base_url'],
                    web_base_path=panel_data.get('web_base_path', '')
                ) as api:

                    if not await api.login():
                        logger.error(f"Failed to login to panel {panel_id}")
                        continue

                    all_inbounds = await api.inbounds()
                    if not all_inbounds:
                        logger.warning(f"No inbounds from panel {panel_id}")
                        continue

                    if assigned_inbound_ids is None:
                        filtered_inbounds = all_inbounds
                    else:
                        filtered_inbounds = [
                            ib for ib in all_inbounds
                            if ib.get('id') in assigned_inbound_ids
                        ]

                    online_clients = set(await api.online_clients())
                    
                    total_used = 0
                    total_capacity = 0
                    has_unlimited = False

                    all_users: Set[str] = set()
                    online_users: Set[str] = set()
                    expiring_users: Set[str] = set()
                    expired_users: Set[str] = set()

                    for inbound in filtered_inbounds:
                        
                        inbound_up = int(inbound.get("up", 0) or 0)
                        inbound_down = int(inbound.get("down", 0) or 0)
                        total_used += (inbound_up + inbound_down)
                        inbound_total_bytes = int(inbound.get("total", 0) or 0)
                        
                        if inbound_total_bytes == 0:
                            has_unlimited = True
                        else:
                            total_capacity += inbound_total_bytes


                        clients = _extract_clients_from_inbound(inbound)

                        for client in clients:
                            email = client.get('email', '')
                            if not email:
                                continue

                            all_users.add(email)

                            if email in online_clients:
                                online_users.add(email)

                            is_expiring, is_expired = _calc_status_for_client(client, now)

                            if is_expired:
                                expired_users.add(email)
                            elif is_expiring:
                                expiring_users.add(email)
                                
                    logger.info(
                        f"📊 Panel '{panel_data['panel_name']}': "
                        f"Total Used={total_used / (1024**3):.2f} GB, "
                        f"Total Capacity={total_capacity / (1024**3):.2f} GB, "
                        f"Unlimited={has_unlimited}, "
                        f"Users={len(all_users)}"
                    )
                    
                    if has_unlimited:
                        remaining = None
                    elif total_capacity > 0:
                        remaining = max(0, total_capacity - total_used)
                    else:
                        remaining = None

                    panels_snapshot[panel_id] = {
                        'panel_name': panel_data['panel_name'],
                        'counts': {
                            'users': len(all_users),
                            'online': len(online_users),
                            'expiring': len(expiring_users),
                            'expired': len(expired_users)
                        },
                        'usage': {
                            'used': total_used,
                            'total': total_capacity,
                            'remaining': remaining,
                            'unlimited': has_unlimited
                        },
                        'lists': {
                            'users': sorted(all_users),
                            'online': sorted(online_users),
                            'expiring': sorted(expiring_users),
                            'expired': sorted(expired_users)
                        }
                    }

            except Exception as e:
                logger.error(f"❌ Error processing panel {panel_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue

        return panels_snapshot

    except Exception as e:
        logger.error(f"❌ Error building snapshot for user {telegram_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}
