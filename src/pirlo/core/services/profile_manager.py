import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class ProfileMetadata:
    name: str
    created_at: str
    updated_at: str
    expires_at: str
    ttl_days: int
    authenticated_urls: list[str]


class ProfileManager:
    """Manages browser profiles, metadata persistence, and session expiration under PIRLO_WORKSPACE."""

    @staticmethod
    def get_workspace_dir() -> Path:
        raw_workspace = os.environ.get("PIRLO_WORKSPACE", "~/.pirlo-pitch")
        path = Path(raw_workspace).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def get_profiles_dir() -> Path:
        profiles_dir = ProfileManager.get_workspace_dir() / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        return profiles_dir

    @classmethod
    def resolve_profile_path(cls, profile_input: str = "default") -> Path:
        """Resolve a profile string to a Path.

        If profile_input looks like an explicit path (starts with '/' or './' or '../'),
        it is resolved as an absolute Path. Otherwise, it is treated as a named profile
        under PIRLO_WORKSPACE/profiles/<name>.
        """
        if not profile_input:
            profile_input = "default"

        if profile_input.startswith(("/", "./", "../", "~")):
            path = Path(profile_input).expanduser().resolve()
        else:
            path = cls.get_profiles_dir() / profile_input

        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_metadata_path(cls, profile_input: str = "default") -> Path:
        profile_path = cls.resolve_profile_path(profile_input)
        return profile_path / "metadata.json"

    @classmethod
    def save_profile_metadata(
        cls,
        profile_input: str = "default",
        urls: list[str] | None = None,
        ttl_days: int = 7,
    ) -> ProfileMetadata:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=ttl_days)

        profile_path = cls.resolve_profile_path(profile_input)
        profile_name = profile_path.name
        metadata_path = profile_path / "metadata.json"

        created_at_str = now.isoformat()
        if metadata_path.exists():
            existing = cls.load_profile_metadata(profile_input)
            if existing and existing.created_at:
                created_at_str = existing.created_at

        # Preserve / merge URLs if new urls provided
        final_urls = list(dict.fromkeys(urls)) if urls else []
        if metadata_path.exists():
            existing = cls.load_profile_metadata(profile_input)
            if existing:
                combined = (existing.authenticated_urls or []) + final_urls
                final_urls = list(dict.fromkeys(combined))

        metadata = ProfileMetadata(
            name=profile_name,
            created_at=created_at_str,
            updated_at=now.isoformat(),
            expires_at=expires.isoformat(),
            ttl_days=ttl_days,
            authenticated_urls=final_urls,
        )

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metadata), f, indent=2)

        return metadata

    @classmethod
    def load_profile_metadata(cls, profile_input: str = "default") -> ProfileMetadata | None:
        metadata_path = cls.get_metadata_path(profile_input)
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            return ProfileMetadata(
                name=data.get("name", cls.resolve_profile_path(profile_input).name),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                expires_at=data.get("expires_at", ""),
                ttl_days=data.get("ttl_days", 7),
                authenticated_urls=data.get("authenticated_urls", []),
            )
        except Exception:  # noqa: BLE001
            return None

    @classmethod
    def exists(cls, profile_input: str = "default") -> bool:
        profile_path = cls.resolve_profile_path(profile_input)
        metadata_path = profile_path / "metadata.json"
        if metadata_path.exists():
            return True
        return any(profile_path.iterdir()) if profile_path.exists() else False

    @classmethod
    def is_expired(cls, profile_input: str = "default") -> bool:
        metadata = cls.load_profile_metadata(profile_input)
        if not metadata or not metadata.expires_at:
            return False

        try:
            expires_dt = datetime.fromisoformat(metadata.expires_at)
            now = datetime.now(timezone.utc)
            return now >= expires_dt
        except Exception:  # noqa: BLE001
            return False

    @classmethod
    def list_profiles(cls) -> list[ProfileMetadata]:
        profiles_dir = cls.get_profiles_dir()
        result = []
        if not profiles_dir.exists():
            return result

        for item in sorted(profiles_dir.iterdir()):
            if item.is_dir():
                meta = cls.load_profile_metadata(item.name)
                if not meta:
                    meta = ProfileMetadata(
                        name=item.name,
                        created_at="",
                        updated_at="",
                        expires_at="",
                        ttl_days=7,
                        authenticated_urls=[],
                    )
                result.append(meta)

        return result

    @classmethod
    def delete_profile(cls, profile_input: str) -> bool:
        profile_path = cls.resolve_profile_path(profile_input)
        if profile_path.exists():
            shutil.rmtree(profile_path)
            return True
        return False
