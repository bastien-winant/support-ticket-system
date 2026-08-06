"""
Databricks App boilerplate:
- Serves a small Flask API
- Reads/writes to Lakebase (Databricks-managed Postgres) via lakebase.py
- Pulls data from the Massive API via massive_client.py and syncs it into Lakebase

Run locally:
    python app.py
Deploy as a Databricks App using app.yaml.
"""

import logging
import os
import re

import requests
from databricks.sdk import WorkspaceClient
from flask import Flask, jsonify, render_template, request

import lakebase
from massive_client import MassiveClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("massive-app")

app = Flask(__name__)
_w = WorkspaceClient()

TICKET_TABLE_NAME = "tickets"
MESSAGE_TABLE_NAME = "messages"

def ensure_ticket_table():
	"""Create the ticket table in Lakebase if it doesn't exist yet."""
	lakebase.run_write(
			f"""
			CREATE TABLE IF NOT EXISTS {TICKET_TABLE_NAME} (
					symbol TEXT NOT NULL,
					email TEXT NOT NULL,
					latest_price NUMERIC,
					updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
					PRIMARY KEY (symbol, email)
			)
			"""
	)


def ensure_message_table():
	"""Create the message table in Lakebase if it doesn't exist yet."""
	lakebase.run_write(
			f"""
			CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE_NAME} (
					symbol TEXT NOT NULL,
					email TEXT NOT NULL,
					latest_price NUMERIC,
					updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
					PRIMARY KEY (symbol, email)
			)
			"""
	)


def _current_user_email() -> str:
	"""
	Resolve the current user's email so the watchlist can be personalized.

	Databricks Apps inject the logged-in user's identity via the
	X-Forwarded-Email header on every request. Fall back to the Databricks
	SDK's current_user API for local development where that header isn't set.
	"""
	header_email = request.headers.get("X-Forwarded-Email")
	if header_email:
		return header_email
	return _w.current_user.me().user_name