"""AI assistant for referral-liability / MIS questions.

Answers natural-language questions about the referral program, wallet liability,
and sales using the Claude API (Anthropic SDK). Falls back to a deterministic
snapshot when ANTHROPIC_API_KEY is not configured, so the endpoint always works.
"""
import json
import os

from fastapi import APIRouter

from ..models import AssistantIn
from . import referrals, reports

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# Per project guidance, default to the latest, most capable Claude model.
MODEL = "claude-opus-4-8"

SYSTEM = (
    "You are the finance & MIS assistant for HSFOODS, a fresh-fruits business with a "
    "lifetime referral & wallet program. Answer the user's question using ONLY the live "
    "JSON data provided in the message. Be concise and concrete; format money as ₹. "
    "Referral terms: 'provisional' = accrued but not yet payable; 'review' = held for "
    "manual checks (self-referral, cap breach, return window, low margin); 'approved' = "
    "credited to a referrer's wallet after delivery + return window; 'outstanding "
    "liability' = provisional + review (money likely owed but not yet realised). "
    "If the data doesn't contain the answer, say so plainly rather than guessing."
)


def _gather_context() -> dict:
    return {
        "referralLiability": referrals.liability(),
        "topReferrers": referrals.referrers()[:10],
        "salesSummary": reports.summary(),
    }


def _offline_answer(question: str, ctx: dict) -> str:
    liab = ctx["referralLiability"]
    sales = ctx["salesSummary"]
    return (
        "⚠️ AI answers are disabled — set ANTHROPIC_API_KEY to enable natural-language "
        "responses. Current snapshot:\n"
        f"• Outstanding referral liability: ₹{liab['outstandingLiability']:.2f} "
        f"(provisional ₹{liab['byState']['provisional']['amount']:.2f} + "
        f"review ₹{liab['byState']['review']['amount']:.2f})\n"
        f"• Paid to wallets (approved): ₹{liab['paidOut']:.2f}\n"
        f"• Sales: ₹{sales['totalRevenue']:.2f} across {sales['totalOrders']} orders "
        f"({sales['customers']} customers)\n"
        f"• Return window: {liab['returnWindowDays']} days · "
        f"margin guard: {int(liab['marginGuardFraction'] * 100)}% of line margin"
    )


@router.post("")
def ask(body: AssistantIn):
    ctx = _gather_context()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"answer": _offline_answer(body.question, ctx), "model": "offline", "configured": False}

    try:
        import anthropic  # imported lazily so the app runs without the dependency

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Live HSFOODS data (JSON):\n{json.dumps(ctx, default=str)}\n\n"
                    f"Question: {body.question}"
                ),
            }],
        )
        answer = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        return {"answer": answer.strip(), "model": message.model, "configured": True}
    except Exception as exc:  # surface config/network errors without 500ing the UI
        return {
            "answer": f"AI assistant error: {exc}\n\n{_offline_answer(body.question, ctx)}",
            "model": MODEL,
            "configured": True,
            "error": True,
        }
