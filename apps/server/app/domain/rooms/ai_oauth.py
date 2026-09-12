from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.persistence.mcp.oauth import (
    OAuthPersistenceError,
    OAuthRepository,
    StoredOAuthAuthorization,
    StoredOAuthAuthorizationCode,
    StoredOAuthClient,
    StoredOAuthToken,
)


class AIControllerOAuthError(RuntimeError):
    pass


class AIControllerOAuthService:
    """Application/domain boundary for web-chat OAuth persistence.

    MCP transport code depends on this service, never on persistence modules directly.
    """

    def __init__(self, repository: OAuthRepository) -> None:
        self.repository = repository

    def _call(self, method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OAuthPersistenceError as exc:
            raise AIControllerOAuthError(str(exc)) from exc

    def create_client(
        self,
        *,
        client_id: str,
        redirect_uris: tuple[str, ...],
        client_name: str | None,
        client_secret_hash: str | None = None,
        now: datetime | None = None,
    ) -> StoredOAuthClient:
        return self._call(
            self.repository.create_client,
            client_id=client_id,
            redirect_uris=redirect_uris,
            client_name=client_name,
            client_secret_hash=client_secret_hash,
            now=now,
        )

    def get_client(self, client_id: str) -> StoredOAuthClient | None:
        return self._call(self.repository.get_client, client_id)

    def replace_authorization_for_grant(
        self,
        *,
        client_id: str,
        grant_id: UUID,
        now: datetime | None = None,
    ) -> StoredOAuthAuthorization:
        return self._call(
            self.repository.replace_authorization_for_grant,
            client_id=client_id,
            grant_id=grant_id,
            now=now,
        )

    def get_authorization(
        self,
        authorization_id: UUID,
    ) -> StoredOAuthAuthorization | None:
        return self._call(self.repository.get_authorization, authorization_id)

    def revoke_authorization(
        self,
        authorization_id: UUID,
        *,
        now: datetime | None = None,
    ) -> None:
        self._call(
            self.repository.revoke_authorization,
            authorization_id,
            now=now,
        )

    def revoke_grant_authorizations(
        self,
        grant_id: UUID,
        *,
        now: datetime | None = None,
    ) -> None:
        self._call(
            self.repository.revoke_grant_authorizations,
            grant_id,
            now=now,
        )

    def create_authorization_code(
        self,
        *,
        code_hash: str,
        authorization_id: UUID,
        code_challenge: str,
        redirect_uri: str,
        expires_at: datetime,
    ) -> StoredOAuthAuthorizationCode:
        return self._call(
            self.repository.create_authorization_code,
            code_hash=code_hash,
            authorization_id=authorization_id,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            expires_at=expires_at,
        )

    def get_authorization_code(
        self,
        code_hash: str,
    ) -> StoredOAuthAuthorizationCode | None:
        return self._call(self.repository.get_authorization_code, code_hash)

    def consume_authorization_code(
        self,
        code_hash: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        return self._call(
            self.repository.consume_authorization_code,
            code_hash,
            now=now,
        )

    def issue_token_pair(
        self,
        *,
        authorization_id: UUID,
        access_hash: str,
        access_expires_at: datetime,
        refresh_hash: str,
        refresh_expires_at: datetime,
    ) -> None:
        self._call(
            self.repository.issue_token_pair,
            authorization_id=authorization_id,
            access_hash=access_hash,
            access_expires_at=access_expires_at,
            refresh_hash=refresh_hash,
            refresh_expires_at=refresh_expires_at,
        )

    def get_token(self, token_hash: str) -> StoredOAuthToken | None:
        return self._call(self.repository.get_token, token_hash)

    def resolve_active_access(
        self,
        token_hash: str,
        *,
        now: datetime | None = None,
        touch: bool = False,
    ) -> tuple[StoredOAuthToken, StoredOAuthAuthorization] | None:
        return self._call(
            self.repository.resolve_active_access,
            token_hash,
            now=now,
            touch=touch,
        )

    def revoke_token_family(
        self,
        token_hash: str,
        *,
        now: datetime | None = None,
    ) -> None:
        self._call(self.repository.revoke_token_family, token_hash, now=now)

    def replace_refresh_token(
        self,
        *,
        presented_hash: str,
        new_refresh_hash: str,
        new_refresh_expires_at: datetime,
        new_access_hash: str,
        new_access_expires_at: datetime,
        now: datetime | None = None,
    ) -> tuple[StoredOAuthAuthorization, bool]:
        return self._call(
            self.repository.replace_refresh_token,
            presented_hash=presented_hash,
            new_refresh_hash=new_refresh_hash,
            new_refresh_expires_at=new_refresh_expires_at,
            new_access_hash=new_access_hash,
            new_access_expires_at=new_access_expires_at,
            now=now,
        )


__all__ = [
    "AIControllerOAuthError",
    "AIControllerOAuthService",
]
