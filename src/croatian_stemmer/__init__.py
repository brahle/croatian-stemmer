"""Croatian stemmer based on the Ljubešić-Pandžić algorithm."""

from importlib.metadata import PackageNotFoundError, version

from .stemmer import stem, stem_text

__all__ = ["stem", "stem_text"]

try:
    __version__ = version("croatian-stemmer")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0+unknown"
