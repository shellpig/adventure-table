from __future__ import annotations

"""Public localization path API shared by runtime and structural gates.

The canonical traversal implementation currently lives in ``localization`` because
``ContentLocalizationCatalog`` predates this facade. Re-exporting the exact same
functions here avoids a second implementation (and therefore semantic drift) while
callers outside that module depend only on a public helper name. A later module
split can move the implementation here without changing those callers.
"""

from app.content.localization import _read_path as read_localization_path
from app.content.localization import _tokens as localization_path_tokens

__all__ = ["localization_path_tokens", "read_localization_path"]
