import time
import random
from django.db import connection
import requests

BATCH_SIZE = 10
MAX_RETRY = 3


# 🔌 Your WhatsApp API (modify this)
def send_whatsapp(phone, message):
    url = "http://mqtt.ezrun.in:3001/send"  # your node bot API

    payload = {
        "phone": "91"+phone,
        "message": message
    }

    response = requests.post(url, json=payload, timeout=10)

    if response.status_code != 200:
        raise Exception(f"Failed to send: {response.text}")

    return True


# 🧠 Fetch next batch safely
def fetch_batch():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, phone, message, user_name, retry_count
            FROM whatsapp_queue
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT %s
        """, [BATCH_SIZE])

        columns = [col[0] for col in cursor.description]
        rows = [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]

    return rows


# ✅ Update status
def update_status(msg_id, status, retry_count=None):
    with connection.cursor() as cursor:
        if retry_count is not None:
            cursor.execute("""
                UPDATE whatsapp_queue
                SET status=%s, retry_count=%s
                WHERE id=%s
            """, [status, retry_count, msg_id])
        else:
            cursor.execute("""
                UPDATE whatsapp_queue
                SET status=%s
                WHERE id=%s
            """, [status, msg_id])


# ✨ Generate personalized message
def generate_message(name, base_message):
    intros = [
        "We found a new project for you:",
        "A new opportunity is available:",
        "You might be interested in this work:"
    ]

    intro = random.choice(intros)

    return f"""
Hi {name},

{intro}
{base_message}

"""


# 🚀 Main worker loop
def process_queue():
    print("🚀 WhatsApp Worker Started...")

    while True:
        rows = fetch_batch()

        if not rows:
            time.sleep(5)
            continue

        for row in rows:
            msg_id = row["id"]
            phone = row["phone"]
            base_message = row["message"]
            name = row["user_name"] or "there"
            retry_count = row["retry_count"]

            try:
                # mark as processing
                update_status(msg_id, "processing")

                # personalize message
                msg = generate_message(name, base_message)

                # simulate typing delay
                time.sleep(random.uniform(1.5, 3.5))

                # send message
                send_whatsapp(phone, msg)

                # mark as sent
                update_status(msg_id, "sent")

                print(f"✅ Sent to {phone}")

                # random delay between messages (3–8 sec)
                time.sleep(random.randint(3, 8))

            except Exception as e:
                print(f"❌ Error sending to {phone}: {e}")

                retry_count += 1

                if retry_count >= MAX_RETRY:
                    update_status(msg_id, "failed", retry_count)
                else:
                    update_status(msg_id, "pending", retry_count)

        # ⏳ delay between batches (50–80 sec)
        batch_delay = random.randint(50, 80)
        print(f"⏳ Batch done. Waiting {batch_delay} sec...\n")
        time.sleep(batch_delay)


# ▶️ Entry point
if __name__ == "__main__":
    process_queue()