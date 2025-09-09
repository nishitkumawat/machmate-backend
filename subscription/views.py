import json
import razorpay
import datetime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
from django.conf import settings

# Setup Razorpay client
razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


@csrf_exempt
def user_subscription(request):
    """Get user's subscription info"""
    user_id = request.session.get("user_id")

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT plan, remaining_credits, subscription_start_date, subscription_end_date
            FROM users WHERE user_id = %s
        """, [user_id])

        row = cursor.fetchone()

        if row:
            data = {
                'plan': row[0],
                'remaining_credits': row[1],
                'start_date': str(row[2]) if row[2] else None,
                'end_date': str(row[3]) if row[3] else None,
            }
            return JsonResponse(data)

    return JsonResponse({'error': 'User not found'}, status=404)


@csrf_exempt
def create_payment(request):
    """Create Razorpay payment order"""
    user_id = request.session.get("user_id")
    data = json.loads(request.body)
    plan = data.get('plan')

    # Plan prices (in paise)
    prices = {'basic': 49900, 'pro': 149900, 'premium': 349900}

    if plan not in prices:
        return JsonResponse({'error': 'Invalid plan'}, status=400)

    # Create Razorpay order
    order = razorpay_client.order.create({
        'amount': prices[plan],
        'currency': 'INR',
        'payment_capture': 1
    })

    # Save payment record (make sure you have subscription_payments table)
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO subscription_payments 
            (user_id, plan, amount, rzp_order_id, status)
            VALUES (%s, %s, %s, %s, 'pending')
        """, [user_id, plan, prices[plan] / 100, order['id']])

    return JsonResponse({
        'order_id': order['id'],
        'amount': order['amount'],
        'currency': order['currency']
    })


@csrf_exempt
def verify_payment(request):
    """Verify payment and activate subscription"""
    user_id = request.session.get("user_id")
    data = json.loads(request.body)

    rzp_order_id = data.get('rzp_order_id')
    rzp_payment_id = data.get('rzp_payment_id')
    rzp_signature = data.get('rzp_signature')
    plan = data.get('plan')

    # Verify payment signature
    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': rzp_order_id,
            'razorpay_payment_id': rzp_payment_id,
            'razorpay_signature': rzp_signature
        })
    except:
        return JsonResponse({'error': 'Payment verification failed'}, status=400)

    # Update payment record
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE subscription_payments 
            SET rzp_payment_id = %s, status = 'success'
            WHERE rzp_order_id = %s AND user_id = %s
        """, [rzp_payment_id, rzp_order_id, user_id])

    # Activate subscription
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(days=30)

    # Credits based on plan
    credits = {'basic': 10, 'pro': 100, 'premium': 9999}

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE users 
            SET plan = %s, remaining_credits = %s, 
                subscription_start_date = %s, subscription_end_date = %s
            WHERE user_id = %s
        """, [plan, credits[plan], start_date, end_date, user_id])

    return JsonResponse({'success': 'Subscription activated!'})


@csrf_exempt
def cancel_subscription(request):
    """Cancel subscription (will not renew after expiry)"""
    user_id = request.session.get("user_id")

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE users 
            SET plan = 'none'
            WHERE user_id = %s
        """, [user_id])

    return JsonResponse({'success': 'Subscription will be canceled after current period'})


@csrf_exempt
def check_credits(request):
    """Check if user has credits available"""
    user_id = request.session.get("user_id")

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT remaining_credits FROM users WHERE user_id = %s
        """, [user_id])

        row = cursor.fetchone()
        has_credits = row[0] > 0 if row else False

    return JsonResponse({'has_credits': has_credits})


@csrf_exempt
def use_credit(request):
    """Use one credit (e.g., when user uploads a quotation)"""
    user_id = request.session.get("user_id")

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE users 
            SET remaining_credits = remaining_credits - 1 
            WHERE user_id = %s AND remaining_credits > 0
        """, [user_id])

        success = cursor.rowcount > 0

    return JsonResponse({'success': success})
