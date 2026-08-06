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

from databricks.sdk import WorkspaceClient
from flask import Flask, jsonify, render_template, request

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("massive-app")

app = Flask(__name__)
_w = WorkspaceClient()

QUEUE_TABLE_NAME = os.environ.get("QUEUE_TABLE_NAME", "watchlist")
MESSAGE_TABLE_NAME = os.environ.get("MESSAGE_TABLE_NAME", "ticker_news")

def ensure_queue_table():
	"""Create the ticket queue table in Lakebase if it doesn't exist yet."""
	lakebase.run_write(
		f"""
		CREATE TABLE IF NOT EXISTS {QUEUE_TABLE_NAME} (
			ticket_id SERIAL PRIMARY KEY,
			title TEXT NOT NULL,
			description TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'OPEN',
			created_by TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
			updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);
		"""
	)


def ensure_message_table():
	"""Create the ticket message table in Lakebase if it doesn't exist yet."""
	ensure_queue_table()
	lakebase.run_write(
		f"""
		CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE_NAME} (
			message_id SERIAL PRIMARY KEY,
			ticket_id INTEGER REFERENCES {QUEUE_TABLE_NAME}(id),
			message_text TEXT NOT NULL,
			author TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);
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
	"""Simple UI to submit a list of support tickets."""
	return render_template("index.html")


@app.route("/queue", methods=["GET"])
def get_queue():
	"""Return the current user's ticket queue, with their last known status."""
	ensure_queue_table()
	email = _current_user_email()
	rows = lakebase.run_query(
		f"SELECT ticket_id, title, description, status, created_by, created_at, updated_at FROM {QUEUE_TABLE_NAME} "
		f"WHERE created_by = %s ORDER BY created_at DESC",
		(email,),
	)
	return jsonify(rows)


@app.route("/queue/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
	"""Return the current user's ticket queue, with their last known status."""
	ensure_queue_table()
	rows = lakebase.run_query(
		f"SELECT ticket_id, title, description, status, created_by, created_at, updated_at FROM {QUEUE_TABLE_NAME} "
		f"WHERE ticket_id = %s",
		(ticket_id,),
	)
	return jsonify(rows)


@app.route("/queue/<ticket_id>/close", methods=["PATCH"])
def close_ticket(ticket_id):
	ensure_queue_table()
	
	if not ticket_id or not ticket_id.isnumeric():
		return jsonify({"error": f"Invalid ticket ID: {ticket_id!r}"}), 400

	lakebase.run_write(
		f"UPDATE {QUEUE_TABLE_NAME} SET status = 'CLOSED' WHERE ticket_id = {ticket_id};",
		(ticket_id),
	)



@app.route("/queue/<ticket_id>", methods=["DELETE"])
def delete_from_queue(ticket_id):
	"""
	Remove a ticket from the current user's queue.
	"""
	ensure_queue_table()
	
	if not ticket_id or not ticket_id.isnumeric():
		return jsonify({"error": f"Invalid ticket ID: {ticket_id!r}"}), 400
	
	lakebase.run_write(
		f"""
		DELETE FROM {QUEUE_TABLE_NAME}
		WHERE ticket_id = %s
		""",
		(ticket_id),
	)
	
	return jsonify({"id": ticket_id, "deleted": True})


@app.route("/queue/<ticket_id>/messages", methods=["GET"])
def get_ticket_messages(ticket_id):
	"""
	Retrieve stored messages for a ticket from the database.
	"""
	ensure_message_table()
	
	if not ticket_id or not ticket_id.isnumeric():
		return jsonify({"error": f"Invalid ticket ID: {ticket_id!r}"}), 400
	
	rows = lakebase.run_query(
		f"""
		SELECT message_id, ticket_id, message_text, author, created_at
		FROM {MESSAGE_TABLE_NAME}
		WHERE ticket_id = %s
		ORDER BY created_at DESC
		LIMIT 20
		""",
		(ticket_id,),
	)
	return jsonify(rows)


@app.route("/queue", methods=["POST"])
def add_to_queue():
	"""
	Add the ticket on the queue in Lakebase.
	"""
	ensure_queue_table()

	# retrieve ticket details from request
	if request.is_json:
		title = request.json.get("title", "")
		description = request.json.get("description", "")
	else:
		title = request.form.get("title", "")
		description = request.form.get("description", "")

	email = _current_user_email()

	lakebase.run_write(
		f"""
		INSERT INTO {QUEUE_TABLE_NAME} (title, description, created_by)
		VALUES (%s, %s, %s)
		""",
		(title, description, email),
	)

	return jsonify({"title": title, "description": description, "created_by": email})


if __name__ == '__main__':
	host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
	port = int(os.getenv('FLASK_RUN_PORT', 8000))
	app.run(debug=True, host=host, port=port)
	print(f"Flask app running on http://{host}:{port}")