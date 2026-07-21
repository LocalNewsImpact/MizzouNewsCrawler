#!/usr/bin/env python3
"""Configure authenticated extraction for a publisher (Source record).

Sets the ``requires_login`` / ``auth_type`` / ``auth_secret_name`` /
``auth_config`` columns on a ``sources`` row so the extractor performs a browser
login before fetching that publisher's (paywalled) articles.

Credentials are NEVER written here — only the non-secret login configuration and
the *name* of the secret that holds the credentials. The credentials themselves
live in GCP Secret Manager (JSON ``{"username": ..., "password": ...}``) or an
environment override, resolved at runtime by
``src.crawler.authenticated_login.resolve_auth_credentials``.

Note: dataset membership is modeled via ``datasets`` + ``dataset_sources`` in
this repo. The optional ``--dataset`` flag verifies that the host belongs to the
intended dataset (for example a WSU dataset); it does not store a free-form tag
on the ``sources`` row.

This must run AFTER the ``f7a2b9c1d3e4`` migration has been applied (the auth
columns must exist).

Examples
--------
Configure The Spokesman-Review (Auth0)::

    python scripts/configure_publisher_auth.py \
        --host www.spokesman.com \
        --dataset WSU Washington State \
        --auth-type auth0 \
        --secret-name publisher-auth-spokesman-com \
        --config '{"auth0_domain": "login.spokesman.com",
                   "client_id": "q2DzLaeGTymklh4RqJhDCm5yKH6poDC7",
                   "redirect_uri": "https://www.spokesman.com/login-redirect/",
                   "scope": "openid profile email",
                   "success_text": "My Account"}'

Configure The Columbian (Newzware SSO)::

    python scripts/configure_publisher_auth.py \
        --host www.columbian.com \
        --dataset WSU Washington State \
        --auth-type newzware \
        --secret-name publisher-auth-columbian-com \
        --config '{"login_url": "https://www.columbian.com/login/",
                   "return_host": "www.columbian.com",
                   "success_text": "Log Out"}'

Configure the Port Townsend Leader (SimpleCirc)::

    python scripts/configure_publisher_auth.py \
        --host www.ptleader.com \
        --dataset WSU Washington State \
        --auth-type simplecirc \
        --secret-name publisher-auth-ptleader-com \
        --config '{"login_url": "https://ptleader.com/login/"}'

Note that SimpleCirc publishers have no password: the secret payload is
``{"username": "<subscriber email>", "zip": "<billing ZIP on the account>"}``.

Configure the Newport Miner (eType metered paywall)::

    python scripts/configure_publisher_auth.py \
        --host www.pendoreillerivervalley.com \
        --dataset WSU Washington State \
        --auth-type etype \
        --secret-name publisher-auth-pendoreillerivervalley-com \
        --config '{"login_url":
                     "https://www.pendoreillerivervalley.com/account/etype-login"}'

eType publishers have a *second*, unrelated site login at ``/account/login``;
subscriber credentials belong to ``/account/etype-login`` and are rejected by
the other one.

Disable authenticated extraction for a publisher::

    python scripts/configure_publisher_auth.py --host www.spokesman.com --disable

Run inside a production pod per the repo's DB access protocol::

    kubectl cp scripts/configure_publisher_auth.py \
        production/<api-pod>:/app/configure_publisher_auth.py
    kubectl exec -n production <api-pod> -- python /app/configure_publisher_auth.py \
        --host www.spokesman.com --auth-type auth0 \
        --secret-name publisher-auth-spokesman-com --config '{...}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure ``src`` package is importable when running from repository root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from src.models.database import DatabaseManager
from src.utils.dataset_utils import resolve_dataset_id


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        required=True,
        help="Source host to configure (must match sources.host exactly, "
        "e.g. www.spokesman.com)",
    )
    parser.add_argument(
        "--dataset",
        help="Optional dataset slug/label/UUID used to verify that this host is "
        "mapped into the intended dataset (for example a WSU dataset)",
    )
    parser.add_argument(
        "--auth-type",
        choices=["auth0", "form", "newzware", "simplecirc", "etype"],
        help="Login mechanism (required unless --disable)",
    )
    parser.add_argument(
        "--secret-name",
        help="Name of the secret holding credentials (required unless --disable)",
    )
    parser.add_argument(
        "--config",
        default="{}",
        help="JSON of non-secret login parameters",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Turn off authenticated extraction for this host",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    db = DatabaseManager()

    dataset_id = None
    if args.dataset:
        try:
            dataset_id = resolve_dataset_id(db.engine, args.dataset)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if args.disable:
        params = {
            "host": args.host,
            "requires_login": False,
            "auth_type": None,
            "auth_secret_name": None,
            "auth_config": None,
            "dataset_id": dataset_id,
        }
    else:
        if not args.auth_type or not args.secret_name:
            print(
                "ERROR: --auth-type and --secret-name are required "
                "(or pass --disable)",
                file=sys.stderr,
            )
            return 2
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as exc:
            print(f"ERROR: --config is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(config, dict):
            print("ERROR: --config must be a JSON object", file=sys.stderr)
            return 2
        params = {
            "host": args.host,
            "requires_login": True,
            "auth_type": args.auth_type,
            "auth_secret_name": args.secret_name,
            "auth_config": json.dumps(config),
            "dataset_id": dataset_id,
        }

    with db.get_session() as session:
        result = session.execute(
            text("""
                UPDATE sources
                SET requires_login = :requires_login,
                    auth_type = :auth_type,
                    auth_secret_name = :auth_secret_name,
                    auth_config = CAST(:auth_config AS JSON)
                WHERE host = :host
                  AND (
                        -- Casts are required: Postgres cannot infer the type of
                        -- a bare parameter used only in an IS NULL test.
                        CAST(:dataset_id AS TEXT) IS NULL OR EXISTS (
                            SELECT 1
                            FROM dataset_sources ds
                            WHERE ds.source_id = sources.id
                              AND ds.dataset_id = CAST(:dataset_id AS TEXT)
                        )
                  )
                """),
            params,
        )
        session.commit()
        updated = result.rowcount

    if not updated:
        scope = f" in dataset {args.dataset!r}" if args.dataset else ""
        print(
            f"No source found with host = {args.host!r}{scope}",
            file=sys.stderr,
        )
        return 1

    state = "disabled" if args.disable else "enabled"
    dataset_note = f" for dataset {args.dataset}" if args.dataset else ""
    print(
        f"Authenticated extraction {state} for {args.host}{dataset_note} "
        f"({updated} row)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
