"""
Databricks App boilerplate:
- Serves a small Flask API
- Reads/writes to Lakebase (Databricks-managed Postgres) via lakebase.py

Run locally:
	python app.py
Deploy as a Databricks App using app.yaml.
"""

import logging
import os

from databricks.sdk import WorkspaceClient
from flask import Flask, jsonify, render_template, request

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("massive-app")

app = Flask(__name__)
_w = WorkspaceClient()

TICKET_TABLE_NAME = os.environ.get("TICKET_TABLE_NAME", "tickets")
MESSAGE_TABLE_NAME = os.environ.get("MESSAGE_TABLE_NAME", "messages")

def ensure_ticket_table():
	"""Create the ticket table in Lakebase if it doesn't exist yet."""
	lakebase.run_write(
		f"""
		CREATE TABLE IF NOT EXISTS {TICKET_TABLE_NAME} (
			ticket_id SERIAL PRIMARY KEY,
			title TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'OPEN',
			created_by TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);
		"""
	)

def ensure_message_table():
	"""Create the message table in Lakebase if it doesn't exist yet."""
	ensure_ticket_table()
	lakebase.run_write(
		f"""
		CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE_NAME} (
			message_id SERIAL PRIMARY KEY,
			ticket_id INTEGER NOT NULL REFERENCES {TICKET_TABLE_NAME} ON DELETE CASCADE,
			message_text TEXT NOT NULL,
			author TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);
		"""
	)


def _current_user_email() -> str:
	"""
	Resolve the current user's email so the queue can be personalized.

	Databricks Apps inject the logged-in user's identity via the
	X-Forwarded-Email header on every request. Fall back to the Databricks
	SDK's current_user API for local development where that header isn't set.
	"""
	header_email = request.headers.get("X-Forwarded-Email")
	if header_email:
		return header_email
	return _w.current_user.me().user_name


@app.route("/healthz")
def healthz():
	return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_exception(err):
	"""Ensure all unhandled errors return JSON (not an HTML error page),
	so the frontend's resp.json() call never chokes on HTML."""
	logger.exception("Unhandled exception while processing request")
	status_code = getattr(err, "code", 500)
	if not isinstance(status_code, int):
		status_code = 500
	return jsonify({"error": str(err)}), status_code


@app.route("/")
def index():
	"""Simple UI to submit submit and view support tickets."""
	return render_template("index.html")


@app.route("/queue", methods=["GET"])
def get_queue():
	"""Return the current user's ticket queue from Lakebase."""
	ensure_ticket_table()
	email = _current_user_email()
	rows = lakebase.run_query(
		f"""SELECT ticket_id, title, status, created_by, created_at FROM {TICKET_TABLE_NAME}
		WHERE created_by = %s ORDER BY created_at DESC""",
		(email,),
	)
	return jsonify(rows)


@app.route("/queue", methods=["POST"])
def add_ticket():
	"""Add a ticket in the current user's queue in Lakebase."""
	ensure_ticket_table()

	if request.is_json:
		title = request.json.get("title", "")
	else:
		title = request.form.get("title", "")

	title = title.strip() if isinstance(title, str) else ""

	if not title:
		return jsonify({"error": f"Invalid title: {title!r}"}), 400

	email = _current_user_email()

	lakebase.run_write(
		f"""
		INSERT INTO {TICKET_TABLE_NAME} (title, created_by)
		VALUES (%s, %s)
		""",
		(title, email),
	)

	return jsonify({"title": title, "created_by": email})


@app.route("/queue/<ticket_id>", methods=["PATCH"])
def close_ticket(ticket_id):
	"""Closes a ticket in the current user's queue in Lakebase."""
	ensure_ticket_table()
	
	if not ticket_id or not ticket_id.isnumeric():
		return jsonify({"error": f"Invalid ticket ID: {ticket_id!r}"}), 400

	lakebase.run_write(
		f"""
		UPDATE {TICKET_TABLE_NAME} SET status = 'CLOSED' WHERE ticket_id = '{ticket_id}';
		"""
	)

	return jsonify({"ticket_id": ticket_id})



@app.route("/queue/<ticket_id>", methods=["DELETE"])
def delete_ticket(ticket_id):
	"""Remove a ticket from the current user's queue in Lakebase."""
	ensure_ticket_table()
	
	if not ticket_id or not ticket_id.isnumeric():
		return jsonify({"error": f"Invalid ticket ID: {ticket_id!r}"}), 400
	
	lakebase.run_write(
		f"""
		DELETE FROM {TICKET_TABLE_NAME}
		WHERE ticket_id = %s
		""",
		(ticket_id,),
	)
	
	return jsonify({"ticket_id": ticket_id, "deleted": True})


@app.route("/queue/<ticket_id>/messages", methods=["GET"])
def get_messages(ticket_id):
	"""
	Retrieve a ticket's messages in Lakebase.
	"""
	ensure_message_table()
	
	if not ticket_id or not ticket_id.isnumeric():
		return jsonify({"error": f"Invalid ticket ID: {ticket_id!r}"}), 400
	
	rows = lakebase.run_query(
		f"""SELECT message_id, ticket_id, message_text, author, created_at FROM {MESSAGE_TABLE_NAME}
		WHERE ticket_id = %s ORDER BY created_at DESC""",
		(ticket_id,),
	)
	return jsonify(rows)


if __name__ == '__main__':
	host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
	port = int(os.getenv('FLASK_RUN_PORT', 8000))
	app.run(debug=True, host=host, port=port)
	print(f"Flask app running on http://{host}:{port}")