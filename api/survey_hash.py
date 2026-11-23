"""Anonymous respondent ids for survey responses (S12).

The id is a keyed hash (HMAC-SHA256 with SURVEY_HASH_SECRET from .env). A plain hash of
(USN, offering) could be reversed by hashing every candidate: USNs follow 1RV<yy>IS<nnn>, so
there are only ~17k pairs. Changing the secret changes every id, so duplicate detection no longer
matches responses stored under the old one.
"""

import hashlib
import hmac

from api import config


def respondent_hash(usn: str, offering_id: int, survey_type: str, key: bytes | None = None) -> str:
    if key is None:
        key = config.survey_hash_secret().encode()
    message = f"{usn}:{offering_id}:{survey_type}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()
