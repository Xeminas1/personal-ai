from __future__ import annotations

import webbrowser

from app.mobile_runtime import ensure_mobile_server_current, mobile_local_url

if not ensure_mobile_server_current():
    raise RuntimeError("XemAi could not start the local support page.")
webbrowser.open(mobile_local_url() + "/support", new=1)
