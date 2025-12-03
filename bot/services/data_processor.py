"""
Core data processing service for client analysis.
"""
import time
import logging
from typing import Dict, List, Tuple

from ..config.settings import (
    EXPIRING_SECONDS_THRESHOLD,
    EXPIRING_BYTES_THRESHOLD
)

logger = logging.getLogger(__name__)

def calculate_client_status(client: dict, now: float) -> Tuple[bool, bool]:
    """
    Calculate if a client is expiring or expired.

    Args:
        client: Client data dict from panel
        now: Current timestamp

    Returns:
        Tuple of (is_expiring, is_expired)
    """
    try:
        
        up = int(client.get("up", 0) or 0)
        down = int(client.get("down", 0) or 0)
        used_bytes = up + down
        
        total_gb_val = client.get("totalGB", 0) or 0
        total_bytes_val = client.get("total", 0) or 0
        
        total_bytes = 0
        if float(total_gb_val or 0) > 0:
            total_bytes = int(float(total_gb_val) * (1024**3))
            logger.debug(f"Using totalGB={total_gb_val}, converted to {total_bytes} bytes")
        elif float(total_bytes_val or 0) > 0:
            total_bytes = int(float(total_bytes_val))
            logger.debug(f"Using total={total_bytes_val} bytes directly")
        else:
            alt_total_gb = client.get("limit", 0) or 0
            if float(alt_total_gb) > 0:
                total_bytes = int(float(alt_total_gb) * (1024**3))
                logger.debug(f"Using alternative totalGB={alt_total_gb}")

        expiry_ms = int(
            client.get("expiryTime", 0) or
            client.get("expire", 0) or
            client.get("expiry", 0) or 0
        )
        now_ts = now
        
        left_bytes = None
        if total_bytes > 0:
            left_bytes = total_bytes - used_bytes
            logger.debug(
                f"Client {client.get('email', 'unknown')}: "
                f"used={used_bytes}, total={total_bytes}, left={left_bytes}"
            )
            
        expired_quota = (left_bytes is not None and left_bytes <= 0)
        expired_time = (expiry_ms > 0 and (expiry_ms / 1000.0) <= now_ts)
        is_expired = expired_quota or expired_time

        logger.debug(
            f"Client {client.get('email', 'unknown')}: "
            f"expired_quota={expired_quota}, expired_time={expired_time}, "
            f"is_expired={is_expired}"
        )
        
        is_expiring = False
        if not is_expired:
            
            expiring_time = False
            if expiry_ms > 0:
                secs_left = (expiry_ms / 1000.0) - now_ts
                if 0 < secs_left <= EXPIRING_SECONDS_THRESHOLD:
                    expiring_time = True
                    logger.debug(f"Client expiring by time: {secs_left:.0f} seconds left")

            expiring_quota = False
            if left_bytes is not None and total_bytes > 0:
                if 0 < left_bytes <= EXPIRING_BYTES_THRESHOLD:
                    expiring_quota = True
                    logger.debug(f"Client expiring by quota: {left_bytes} bytes left")

            if expiring_time or expiring_quota:
                is_expiring = True

        logger.debug(
            f"Client {client.get('email', 'unknown')}: "
            f"is_expiring={is_expiring}, is_expired={is_expired}"
        )

        return is_expiring, is_expired

    except (ValueError, TypeError, KeyError) as e:
        logger.warning(
            f"Error calculating status for client {client.get('email', 'unknown')}: {e}"
        )
        logger.debug(f"Client data: {client}")
        return False, False

def extract_clients_from_inbound(inbound: dict) -> List[dict]:
    """
    Extract client data from an inbound configuration.
    Tries multiple possible locations.

    Args:
        inbound: Inbound data dict from panel

    Returns:
        List of client dicts
    """
    import json

    clients = []

    if not isinstance(inbound, dict):
        logger.warning("Inbound is not a dict")
        return clients

    inbound_id = inbound.get('id', 'unknown')
    
    if 'clientStats' in inbound and isinstance(inbound['clientStats'], list):
        clients = inbound['clientStats']
        logger.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in 'clientStats'")
        
    elif 'settings' in inbound:
        try:
            if isinstance(inbound['settings'], str):
                settings = json.loads(inbound['settings'])
            else:
                settings = inbound['settings']

            if isinstance(settings, dict) and 'clients' in settings:
                if isinstance(settings['clients'], list):
                    clients = settings['clients']
                    logger.debug(
                        f"Inbound {inbound_id}: Found {len(clients)} clients in 'settings.clients'"
                    )
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Inbound {inbound_id}: Error parsing settings: {e}")

    elif 'clients' in inbound and isinstance(inbound['clients'], list):
        clients = inbound['clients']
        logger.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in direct 'clients' key")
        
    elif 'client_list' in inbound and isinstance(inbound['client_list'], list):
        clients = inbound['client_list']
        logger.debug(f"Inbound {inbound_id}: Found {len(clients)} clients in 'client_list'")
        
    valid_clients = [c for c in clients if isinstance(c, dict)]
    invalid_count = len(clients) - len(valid_clients)

    if invalid_count > 0:
        logger.debug(f"Inbound {inbound_id}: {invalid_count} invalid clients filtered out")
        
    for i, client in enumerate(valid_clients[:3]):
        email = client.get('email', 'no-email')
        total_gb = client.get('totalGB', client.get('total', 'N/A'))
        logger.debug(
            f"  Client {i+1}: {email}, total={total_gb}, "
            f"has 'up'={'up' in client}, has 'down'={'down' in client}"
        )

    return valid_clients
