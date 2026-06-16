import asyncio
import os
from subscription import requires_subscription
from io import BytesIO
from dotenv import load_dotenv
from telegram import Bot, InputFile
from telegram.error import TelegramError
from pdf_builder import build_pdf
from state import GraphState

load_dotenv()

TELEGRAM_BOT_TOKEN:  str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")


async def _send_document_to_telegram(pdf_buffer: BytesIO, run_id: str) -> str:
    if not TELEGRAM_BOT_TOKEN:
        return "failed: TELEGRAM_BOT_TOKEN not set in environment"
    if not TELEGRAM_CHANNEL_ID:
        return "failed: TELEGRAM_CHANNEL_ID not set in environment"

    filename = f"alpha_intel_{run_id}.pdf"
    caption  = (
        f"📊 *Alpha Signals Intelligence Report*\n"
        f"Run ID: `{run_id}`\n"
        f"_Automated report from the MAS pipeline._"
    )

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        async with bot:
            await bot.send_document(
                chat_id=TELEGRAM_CHANNEL_ID,
                document=InputFile(pdf_buffer, filename=filename),
                caption=caption,
                parse_mode="Markdown",
            )
        return "success"
    except TelegramError as e:
        return f"failed: TelegramError — {e.message}"
    except Exception as e:
        return f"failed: Unexpected error — {str(e)}"

@requires_subscription
def broadcaster_node(state: GraphState) -> dict:
    print(f"\n[Agent E — Broadcaster] Starting. Building PDF for run_id={state.run_id}.")

    if not state.report_markdown:
        print("[Agent E — Broadcaster] WARNING: report_markdown is empty. Aborting.")
        return {"broadcast_result": "failed: report_markdown was empty"}

    try:
        pdf_buffer = build_pdf(
            report_markdown=state.report_markdown,
            run_id=state.run_id
        )
        print(f"[Agent E — Broadcaster] PDF built. Size: {pdf_buffer.getbuffer().nbytes:,} bytes.")
    except Exception as e:
        print(f"[Agent E — Broadcaster] ❌ PDF generation failed: {e}")
        return {"broadcast_result": f"failed: PDF build error — {str(e)}"}

    result = asyncio.run(_send_document_to_telegram(pdf_buffer, state.run_id))

    if result == "success":
        print(f"[Agent E — Broadcaster] ✅ PDF transmitted to {TELEGRAM_CHANNEL_ID}.")
    else:
        print(f"[Agent E — Broadcaster] ❌ Transmission failed: {result}")

    return {"broadcast_result": result}