"""Names the workbench never reads, searches, writes or shows the content of.

Every pattern lives here, in one place. Names are matched against every
component of a path (so a folder named `secrets/` protects what is inside),
case-insensitively, because the Mac's disk usually ignores case: `.ENV` is
the same file as `.env`.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

# Environment files hold API keys and passwords. The documented templates
# that projects commit on purpose stay readable.
_ENV_FILES = (".env", ".env.*", ".envrc")
_ENV_ALLOWED = (".env.example", ".env.sample")

# Private keys, certificates and key stores, including SSH keys by their
# default names and Apple's App Store Connect keys (.p8).
_KEYS = (
    "*.pem",
    "*.key",
    "*.p8",
    "*.p12",
    "*.pfx",
    "*.ppk",
    "*.keystore",
    "*.jks",
    "id_rsa*",
    "id_dsa*",
    "id_ed25519*",
    "id_ecdsa*",
)

# Files where tools keep logins and tokens for package registries, git
# remotes and web servers.
_CREDENTIAL_FILES = (
    ".netrc",
    "_netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".htpasswd",
    ".dockercfg",
)

# Folders that hold a person's keys and cloud logins; nothing inside them
# is ever touched.
_SECRET_FOLDERS = (".ssh", ".aws", ".gnupg", ".kube", ".azure")

# Anything named like credentials or secrets, Terraform variables and
# state (which carry passwords in plain text), and cloud service-account
# JSON keys (Google, Firebase, OAuth client secrets).
_SECRET_NAMES = (
    "credentials*",
    "secrets*",
    "*.tfvars",
    "*.tfvars.json",
    "*.tfstate",
    "*.tfstate.*",
    "*service-account*.json",
    "*service_account*.json",
    "*firebase-adminsdk*.json",
    "client_secret*.json",
)

# Mobile signing: provisioning profiles and the Android signing settings
# that hold the key store's passwords.
_SIGNING = (
    "*.mobileprovision",
    "*.provisionprofile",
    "key.properties",
    "keystore.properties",
    "signing.properties",
)

_PATTERNS = _ENV_FILES + _KEYS + _CREDENTIAL_FILES + _SECRET_FOLDERS + _SECRET_NAMES + _SIGNING


def is_protected_name(name: str) -> bool:
    """True when this one file or folder name is protected."""
    folded = name.casefold()
    if folded in _ENV_ALLOWED:
        return False
    return any(fnmatchcase(folded, pattern) for pattern in _PATTERNS)


def is_protected(rel: PurePosixPath) -> bool:
    """True when any component of this project-relative path is protected."""
    return any(is_protected_name(part) for part in rel.parts)


# Writes never go into git's own folder, and never into the folders that
# projects commonly point git's hooks at (`core.hooksPath`).
GIT_DIR = ".git"
HOOK_FOLDERS = (".githooks", ".husky")


def is_git_internal(rel: PurePosixPath) -> bool:
    """True when the path is inside, or is, a `.git` folder or file."""
    return any(part.casefold() == GIT_DIR for part in rel.parts)
