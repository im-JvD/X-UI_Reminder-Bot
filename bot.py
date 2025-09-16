def analyze_inbound(ib, online_emails):
    stats = {"users": 0, "up": 0, "down": 0, "online": 0, "expiring": [], "expired": []}
    if not isinstance(ib, dict):
        return stats

    inbound_id = ib.get("id")
    if not inbound_id:
        return stats

    # گرفتن مصرف واقعی از API
    traffics = api.client_traffics(inbound_id)

    settings = ib.get("settings")
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except Exception:
            settings = {}
    if not isinstance(settings, dict):
        settings = {}

    clients = settings.get("clients", ib.get("clients", []))
    for c in clients:
        stats["users"] += 1
        email = c.get("email", "unknown")

        up = traffics.get(email, {}).get("up", 0)
        down = traffics.get(email, {}).get("down", 0)
        stats["up"] += up
        stats["down"] += down

        if email in online_emails:
            stats["online"] += 1

        quota = int(c.get("total", 0) or c.get("totalGB", 0))
        used = up + down
        left = quota - used if quota > 0 else None

        exp = int(c.get("expiryTime", 0) or c.get("expire", 0))
        rem = (exp / 1000) - time.time() if exp > 0 else None

        if (rem is not None and rem <= 0) or (left is not None and left <= 0):
            stats["expired"].append(email)
        elif (left is not None and left <= 1024**3) or (rem is not None and 0 < rem <= 24 * 3600):
            stats["expiring"].append(email)

    return stats