from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.persistence.mcp.tables import (
    ai_oauth_authorization_codes,
    ai_oauth_authorizations,
    ai_oauth_clients,
    ai_oauth_tokens,
)
from app.persistence.rooms.tables import ai_controller_grants


@dataclass(frozen=True)
class StoredOAuthClient:
    id: UUID
    client_id: str
    client_secret_hash: str | None
    redirect_uris: tuple[str, ...]
    client_name: str | None
    created_at: datetime


@dataclass(frozen=True)
class StoredOAuthAuthorization:
    id: UUID
    client_id: str
    grant_id: UUID
    grant_generation: int
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class StoredOAuthAuthorizationCode:
    code_hash: str
    authorization_id: UUID
    code_challenge: str
    redirect_uri: str
    expires_at: datetime
    consumed_at: datetime | None


@dataclass(frozen=True)
class StoredOAuthToken:
    id: UUID
    token_hash: str
    kind: str
    authorization_id: UUID
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class OAuthPersistenceError(RuntimeError):
    pass


class OAuthRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _client(row) -> StoredOAuthClient | None:
        if row is None:
            return None
        values = dict(row)
        values["redirect_uris"] = tuple(values["redirect_uris"])
        return StoredOAuthClient(**values)

    @staticmethod
    def _authorization(row) -> StoredOAuthAuthorization | None:
        return StoredOAuthAuthorization(**dict(row)) if row is not None else None

    @staticmethod
    def _code(row) -> StoredOAuthAuthorizationCode | None:
        return StoredOAuthAuthorizationCode(**dict(row)) if row is not None else None

    @staticmethod
    def _token(row) -> StoredOAuthToken | None:
        return StoredOAuthToken(**dict(row)) if row is not None else None

    def create_client(
        self,
        *,
        client_id: str,
        redirect_uris: tuple[str, ...],
        client_name: str | None,
        client_secret_hash: str | None = None,
        now: datetime | None = None,
    ) -> StoredOAuthClient:
        now = self._utc(now or datetime.now(timezone.utc))
        client_uuid = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                insert(ai_oauth_clients).values(
                    id=client_uuid,
                    client_id=client_id,
                    client_secret_hash=client_secret_hash,
                    redirect_uris=list(redirect_uris),
                    client_name=client_name,
                    created_at=now,
                )
            )
            row = connection.execute(
                select(ai_oauth_clients).where(ai_oauth_clients.c.id == client_uuid)
            ).mappings().one()
        return self._client(row)  # type: ignore[return-value]

    def get_client(self, client_id: str) -> StoredOAuthClient | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(ai_oauth_clients).where(ai_oauth_clients.c.client_id == client_id)
            ).mappings().one_or_none()
        return self._client(row)

    def replace_authorization_for_grant(
        self,
        *,
        client_id: str,
        grant_id: UUID,
        now: datetime | None = None,
    ) -> StoredOAuthAuthorization:
        now = self._utc(now or datetime.now(timezone.utc))
        authorization_id = uuid4()
        with self.engine.begin() as connection:
            grant = connection.execute(
                select(
                    ai_controller_grants.c.id,
                    ai_controller_grants.c.generation,
                    ai_controller_grants.c.status,
                )
                .where(ai_controller_grants.c.id == grant_id)
                .with_for_update()
            ).one_or_none()
            if grant is None or grant.status != "active":
                raise OAuthPersistenceError("AI controller grant is not active")
            client_exists = connection.scalar(
                select(ai_oauth_clients.c.client_id).where(
                    ai_oauth_clients.c.client_id == client_id
                )
            )
            if client_exists is None:
                raise OAuthPersistenceError("OAuth client is unknown")
            connection.execute(
                update(ai_oauth_authorizations)
                .where(
                    ai_oauth_authorizations.c.grant_id == grant_id,
                    ai_oauth_authorizations.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            connection.execute(
                insert(ai_oauth_authorizations).values(
                    id=authorization_id,
                    client_id=client_id,
                    grant_id=grant_id,
                    grant_generation=int(grant.generation),
                    created_at=now,
                    revoked_at=None,
                )
            )
            row = connection.execute(
                select(ai_oauth_authorizations).where(
                    ai_oauth_authorizations.c.id == authorization_id
                )
            ).mappings().one()
        return self._authorization(row)  # type: ignore[return-value]

    def get_authorization(self, authorization_id: UUID) -> StoredOAuthAuthorization | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(ai_oauth_authorizations).where(
                    ai_oauth_authorizations.c.id == authorization_id
                )
            ).mappings().one_or_none()
        return self._authorization(row)

    def revoke_authorization(
        self,
        authorization_id: UUID,
        *,
        now: datetime | None = None,
    ) -> None:
        now = self._utc(now or datetime.now(timezone.utc))
        with self.engine.begin() as connection:
            connection.execute(
                update(ai_oauth_authorizations)
                .where(
                    ai_oauth_authorizations.c.id == authorization_id,
                    ai_oauth_authorizations.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )

    def revoke_grant_authorizations(
        self,
        grant_id: UUID,
        *,
        now: datetime | None = None,
    ) -> None:
        now = self._utc(now or datetime.now(timezone.utc))
        with self.engine.begin() as connection:
            connection.execute(
                update(ai_oauth_authorizations)
                .where(
                    ai_oauth_authorizations.c.grant_id == grant_id,
                    ai_oauth_authorizations.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
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
        expires_at = self._utc(expires_at)
        with self.engine.begin() as connection:
            connection.execute(
                insert(ai_oauth_authorization_codes).values(
                    code_hash=code_hash,
                    authorization_id=authorization_id,
                    code_challenge=code_challenge,
                    redirect_uri=redirect_uri,
                    expires_at=expires_at,
                    consumed_at=None,
                )
            )
            row = connection.execute(
                select(ai_oauth_authorization_codes).where(
                    ai_oauth_authorization_codes.c.code_hash == code_hash
                )
            ).mappings().one()
        return self._code(row)  # type: ignore[return-value]

    def get_authorization_code(self, code_hash: str) -> StoredOAuthAuthorizationCode | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(ai_oauth_authorization_codes).where(
                    ai_oauth_authorization_codes.c.code_hash == code_hash
                )
            ).mappings().one_or_none()
        return self._code(row)

    def consume_authorization_code(
        self,
        code_hash: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        now = self._utc(now or datetime.now(timezone.utc))
        with self.engine.begin() as connection:
            result = connection.execute(
                update(ai_oauth_authorization_codes)
                .where(
                    ai_oauth_authorization_codes.c.code_hash == code_hash,
                    ai_oauth_authorization_codes.c.consumed_at.is_(None),
                    ai_oauth_authorization_codes.c.expires_at > now,
                )
                .values(consumed_at=now)
            )
        return result.rowcount == 1

    def issue_token_pair(
        self,
        *,
        authorization_id: UUID,
        access_hash: str,
        access_expires_at: datetime,
        refresh_hash: str,
        refresh_expires_at: datetime,
    ) -> None:
        access_expires_at = self._utc(access_expires_at)
        refresh_expires_at = self._utc(refresh_expires_at)
        with self.engine.begin() as connection:
            authorization_active = connection.scalar(
                select(ai_oauth_authorizations.c.id).where(
                    ai_oauth_authorizations.c.id == authorization_id,
                    ai_oauth_authorizations.c.revoked_at.is_(None),
                )
            )
            if authorization_active is None:
                raise OAuthPersistenceError("OAuth authorization is revoked or unknown")
            connection.execute(
                insert(ai_oauth_tokens),
                [
                    {
                        "id": uuid4(),
                        "token_hash": access_hash,
                        "kind": "access",
                        "authorization_id": authorization_id,
                        "expires_at": access_expires_at,
                        "revoked_at": None,
                        "last_used_at": None,
                    },
                    {
                        "id": uuid4(),
                        "token_hash": refresh_hash,
                        "kind": "refresh",
                        "authorization_id": authorization_id,
                        "expires_at": refresh_expires_at,
                        "revoked_at": None,
                        "last_used_at": None,
                    },
                ],
            )

    def get_token(self, token_hash: str) -> StoredOAuthToken | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(ai_oauth_tokens).where(ai_oauth_tokens.c.token_hash == token_hash)
            ).mappings().one_or_none()
        return self._token(row)

    def resolve_active_access(
        self,
        token_hash: str,
        *,
        now: datetime | None = None,
        touch: bool = False,
    ) -> tuple[StoredOAuthToken, StoredOAuthAuthorization] | None:
        now = self._utc(now or datetime.now(timezone.utc))
        context = self.engine.begin() if touch else self.engine.connect()
        with context as connection:
            token_row = connection.execute(
                select(ai_oauth_tokens).where(
                    ai_oauth_tokens.c.token_hash == token_hash,
                    ai_oauth_tokens.c.kind == "access",
                    ai_oauth_tokens.c.revoked_at.is_(None),
                    ai_oauth_tokens.c.expires_at > now,
                )
            ).mappings().one_or_none()
            if token_row is None:
                return None
            auth_row = connection.execute(
                select(ai_oauth_authorizations).where(
                    ai_oauth_authorizations.c.id == token_row["authorization_id"],
                    ai_oauth_authorizations.c.revoked_at.is_(None),
                )
            ).mappings().one_or_none()
            if auth_row is None:
                return None
            if touch:
                connection.execute(
                    update(ai_oauth_tokens)
                    .where(ai_oauth_tokens.c.id == token_row["id"])
                    .values(last_used_at=now)
                )
        return self._token(token_row), self._authorization(auth_row)  # type: ignore[return-value]

    def revoke_token_family(self, token_hash: str, *, now: datetime | None = None) -> None:
        now = self._utc(now or datetime.now(timezone.utc))
        with self.engine.begin() as connection:
            authorization_id = connection.scalar(
                select(ai_oauth_tokens.c.authorization_id).where(
                    ai_oauth_tokens.c.token_hash == token_hash
                )
            )
            if authorization_id is None:
                return
            connection.execute(
                update(ai_oauth_authorizations)
                .where(
                    ai_oauth_authorizations.c.id == authorization_id,
                    ai_oauth_authorizations.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )

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
        now = self._utc(now or datetime.now(timezone.utc))
        new_refresh_expires_at = self._utc(new_refresh_expires_at)
        new_access_expires_at = self._utc(new_access_expires_at)
        with self.engine.begin() as connection:
            token_row = connection.execute(
                select(ai_oauth_tokens)
                .where(
                    ai_oauth_tokens.c.token_hash == presented_hash,
                    ai_oauth_tokens.c.kind == "refresh",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if token_row is None:
                raise OAuthPersistenceError("refresh token is unknown")
            auth_row = connection.execute(
                select(ai_oauth_authorizations)
                .where(ai_oauth_authorizations.c.id == token_row["authorization_id"])
                .with_for_update()
            ).mappings().one_or_none()
            authorization = self._authorization(auth_row)
            if authorization is None:
                raise OAuthPersistenceError("refresh token authorization is unknown")
            if token_row["revoked_at"] is not None:
                if authorization.revoked_at is None:
                    connection.execute(
                        update(ai_oauth_authorizations)
                        .where(ai_oauth_authorizations.c.id == authorization.id)
                        .values(revoked_at=now)
                    )
                return authorization, True
            if (
                authorization.revoked_at is not None
                or self._utc(token_row["expires_at"]) <= now
            ):
                raise OAuthPersistenceError("refresh token is invalid")
            connection.execute(
                update(ai_oauth_tokens)
                .where(ai_oauth_tokens.c.id == token_row["id"])
                .values(revoked_at=now, last_used_at=now)
            )
            connection.execute(
                insert(ai_oauth_tokens),
                [
                    {
                        "id": uuid4(),
                        "token_hash": new_access_hash,
                        "kind": "access",
                        "authorization_id": authorization.id,
                        "expires_at": new_access_expires_at,
                        "revoked_at": None,
                        "last_used_at": None,
                    },
                    {
                        "id": uuid4(),
                        "token_hash": new_refresh_hash,
                        "kind": "refresh",
                        "authorization_id": authorization.id,
                        "expires_at": new_refresh_expires_at,
                        "revoked_at": None,
                        "last_used_at": None,
                    },
                ],
            )
        return authorization, False


__all__ = [
    "OAuthPersistenceError",
    "OAuthRepository",
    "StoredOAuthAuthorization",
    "StoredOAuthAuthorizationCode",
    "StoredOAuthClient",
    "StoredOAuthToken",
]
