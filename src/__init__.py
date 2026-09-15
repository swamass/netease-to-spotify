from . import spotify as spotify
from .matcher_policy import apply as _apply_matcher_policy
from .artist_bound_rank_fallback import apply as _apply_artist_bound_rank_fallback
from .cross_language_retrieval import apply as _apply_cross_language_retrieval

_apply_matcher_policy(spotify)
_apply_artist_bound_rank_fallback(spotify)
_apply_cross_language_retrieval(spotify)
