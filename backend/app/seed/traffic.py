"""Replay a few conversations through the real agent so the dashboard is not empty.

These are not imported metrics. The numbers on the metrics page are counted
from the rows this creates.
"""

from sqlalchemy.orm import Session

from app.agent.engine import Agent, record_csat


SCRIPTS = [
    ("web", None, "How long do I have to return something?", "up"),
    ("web", None, "How much is ground shipping?", "up"),
    ("web", None, "How should I wash linen tea towels?", None),
    ("web", None, "Do you price-match Williams Sonoma?", "down"),
    ("web", None, "Where is MH-31003? Email theo.lang@example.com", "up"),
    ("web", None, "What Hale Pantry plan is on MH-31012? Postcode 60614.", None),
    ("web", None, "Can you reset my password?", "up"),
    ("web", None, "Refund order MH-31004. Email amira.hassan@example.com", None),
    ("web", None, "This is ridiculous and unacceptable.", None),
    ("web", None, "I am opening a chargeback with my bank.", None),
    ("web", None, "The enamel pot burned my hand and I went to a clinic.", None),
    ("web", None, "My lawyer will be in touch about a late package.", None),
    ("web", None, "Please transfer me to a human.", None),
    ("web", None, "I need help with MH-31013. Email priya.shah@example.com", None),
    ("email", "hannah.cho@example.com", "How do I dry linen without a dryer?", "up"),
]


def seed_traffic(session: Session, agent: Agent) -> None:
    for channel, sender, text, vote in SCRIPTS:
        result = agent.handle(
            session,
            text=text,
            channel=channel,
            email_from=sender,
            email_subject="Help" if channel == "email" else None,
        )
        if vote:
            record_csat(session, result["conversation_id"], vote)
