from aiocryptopay import AioCryptoPay, Networks
from config import CRYPTO_BOT_TOKEN
import logging

logger = logging.getLogger(__name__)

crypto = AioCryptoPay(token=CRYPTO_BOT_TOKEN, network=Networks.MAIN_NET)

async def create_invoice(user_id, amount_usdt):
    try:
        invoice = await crypto.create_invoice(
            asset='USDT',
            amount=amount_usdt,
            description="Impulse Terminal: 1 Month Access",
            payload=str(user_id),
            allow_comments=False,
            expires_in=3600
        )
        return invoice
    except Exception as e:
        logger.error(f"CryptoPay Error: {e}")
        return None

async def check_invoice(invoice_id):
    try:
        invoices = await crypto.get_invoices(invoice_ids=invoice_id)
        if invoices:
            return invoices[0]
        return None
    except Exception as e:
        logger.error(f"Check Invoice Error: {e}")
        return None

async def close_session():
    await crypto.close()