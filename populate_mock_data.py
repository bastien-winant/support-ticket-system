#!/usr/bin/env python3
"""
Populate the support ticket system with realistic mock data.
Run this script with: python populate_mock_data.py
"""

import base64
import os
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient

def get_lakebase_url():
    """Fetch and decode the Lakebase connection URL from secrets."""
    w = WorkspaceClient()
    scope = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
    key = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")
    secret = w.secrets.get_secret(scope=scope, key=key)
    return base64.b64decode(secret.value).decode("utf-8")

def main():
    # Get current user
    w = WorkspaceClient()
    current_user = w.current_user.me().user_name
    
    print(f"Creating mock data for user: {current_user}\n")
    
    # Get database connection
    conn = psycopg2.connect(get_lakebase_url(), cursor_factory=RealDictCursor)
    
    try:
        # Ensure tables exist
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id SERIAL PRIMARY KEY,
                    ticket_id INTEGER NOT NULL REFERENCES tickets ON DELETE CASCADE,
                    message_text TEXT NOT NULL,
                    author TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            conn.commit()
        
        # Mock ticket data with messages
        mock_data = [
            {
                "title": "Cannot access production cluster - urgent",
                "status": "OPEN",
                "days_ago": 2,
                "messages": [
                    ("I've checked the cluster settings and it seems the cluster was terminated yesterday evening. Was this intentional?", 0.5),
                    ("The cluster termination was part of our cost optimization initiative. I've restarted it for you. It should be available in about 5 minutes.", 0.2)
                ]
            },
            {
                "title": "Data pipeline failing on weekends",
                "status": "OPEN",
                "days_ago": 5,
                "messages": [
                    ("Looking at the logs, it appears the upstream data source isn't available on weekends. Have you checked with the data provider?", 0.8),
                    ("Good catch! I'll reach out to the vendor about weekend data availability.", 0.3),
                    ("Update: The vendor confirmed they don't publish data on weekends. I'll adjust the pipeline schedule.", 0.1)
                ]
            },
            {
                "title": "Dashboard loading slowly for large datasets",
                "status": "CLOSED",
                "days_ago": 10,
                "messages": [
                    ("I've optimized the underlying queries and added caching. Could you test it again?", 0.7),
                    ("Much better! It now loads in under 10 seconds. Thanks for the quick turnaround!", 0.3)
                ]
            },
            {
                "title": "Need permissions for new Unity Catalog schema",
                "status": "OPEN",
                "days_ago": 1,
                "messages": [
                    ("I can help with that. Just to confirm - you need CREATE TABLE and USE SCHEMA on main.marketing_analytics, correct?", 0.4),
                    ("Yes, that's correct. Also, if possible, could you grant the same permissions to our team's service principal?", 0.2),
                    ("Permissions granted for both your user and the service principal. You should be all set!", 0.1)
                ]
            }
        ]
        
        # Create tickets and messages
        total_tickets = 0
        total_messages = 0
        
        for ticket_data in mock_data:
            # Create ticket
            ticket_created_at = datetime.now() - timedelta(days=ticket_data['days_ago'])
            
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tickets (title, status, created_by, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING ticket_id
                    """,
                    (ticket_data['title'], ticket_data['status'], current_user, ticket_created_at)
                )
                result = cur.fetchone()
                ticket_id = result['ticket_id']
                conn.commit()
            
            total_tickets += 1
            print(f"✓ Created ticket #{ticket_id}: {ticket_data['title']}")
            
            # Add messages to this ticket
            for message_text, days_offset_fraction in ticket_data['messages']:
                # Calculate message timestamp (after ticket creation)
                message_created_at = ticket_created_at + timedelta(days=days_offset_fraction)
                
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO messages (ticket_id, message_text, author, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (ticket_id, message_text, current_user, message_created_at)
                    )
                    conn.commit()
                
                total_messages += 1
                print(f"  ✓ Added message")
            
            print()
        
        print(f"\n{'='*60}")
        print(f"Summary:")
        print(f"  • Created {total_tickets} tickets")
        print(f"  • Added {total_messages} messages")
        print(f"  • Average: {total_messages/total_tickets:.1f} messages per ticket")
        print(f"{'='*60}")
        print(f"\nRefresh your app to see the new data!")
    
    finally:
        conn.close()

if __name__ == "__main__":
    main()
