from pathlib import Path
import traceback

try:
    from ui import main
    raise SystemExit(main())
except SystemExit:
    raise
except Exception:
    path = Path(__file__).resolve().parent / "logs" / "desktop_startup_error.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(traceback.format_exc(), encoding="utf-8")
    raise
