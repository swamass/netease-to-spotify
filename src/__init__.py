from . import spotify as spotify
from .matcher_policy import apply as _apply_matcher_policy
from .artist_bound_rank_fallback import apply as _apply_artist_bound_rank_fallback

_apply_matcher_policy(spotify)
_apply_artist_bound_rank_fallback(spotify)
