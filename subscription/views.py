import json
import razorpay # type: ignore
import datetime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.core.mail import send_mail

# Setup Razorpay client
razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


@csrf_exempt
@require_http_methods(["GET"])
def user_subscription(request):
    """Get user's subscription info"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT plan, remaining_credits, subscription_start_date, subscription_end_date
            FROM users WHERE user_id = %s
        """, [user_id])

        row = cursor.fetchone()

    if row:
        return JsonResponse({
            'plan': row[0],
            'remaining_credits': row[1],
            'start_date': str(row[2]) if row[2] else None,
            'end_date': str(row[3]) if row[3] else None,
        })

    return JsonResponse({'error': 'User not found'}, status=404)


@csrf_exempt
@require_http_methods(["POST"])
def create_payment(request):
    """Create Razorpay payment order"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)
    
    try:
        data = json.loads(request.body)
        plan = data.get('plan')
        
        if not plan:
            return JsonResponse({'error': 'Plan parameter is required'}, status=400)

        # Plan prices (in paise)
        prices = {'basic': 49900, 'pro': 149900, 'premium': 349900}
        if plan not in prices:
            return JsonResponse({'error': 'Invalid plan'}, status=400)

        # Check if user already has this plan active
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT plan, subscription_end_date FROM users WHERE user_id = %s
            """, [user_id])
            user_data = cursor.fetchone()
            
            if user_data and user_data[0] == plan and user_data[1] and user_data[1] > datetime.date.today():
                return JsonResponse({'error': 'You already have an active subscription for this plan'}, status=400)

        # Create Razorpay order
        try:
            order = razorpay_client.order.create({
                'amount': prices[plan],
                'currency': 'INR',
                'payment_capture': 1,
                'notes': {
                    'plan': plan,
                    'user_id': user_id
                }
            })
        except Exception as e:
            return JsonResponse({'error': f'Razorpay order creation failed: {str(e)}'}, status=500)

        # Save transaction in DB
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO subscription_transactions
                (user_id, plan, amount, razorpay_order_id, status, created_at)
                VALUES (%s, %s, %s, %s, 'pending', %s)
            """, [user_id, plan, prices[plan]/100, order['id'], datetime.datetime.now()])

        return JsonResponse({
            'order_id': order['id'],
            'amount': order['amount'],
            'currency': order['currency']
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def verify_payment(request):
    """Verify payment and activate subscription"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)
    
    try:
        data = json.loads(request.body)
        
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        plan = data.get('plan')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature, plan]):
            return JsonResponse({'error': 'Missing required parameters'}, status=400)

        # Verify payment signature
        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
            # Update transaction status to failed
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE subscription_transactions
                    SET status = 'failed', updated_at = %s
                    WHERE razorpay_order_id = %s AND user_id = %s
                """, [datetime.datetime.now(), razorpay_order_id, user_id])
            
            return JsonResponse({'success': False, 'error': 'Payment verification failed'}, status=400)

        # Check if this order has already been processed
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT status FROM subscription_transactions 
                WHERE razorpay_order_id = %s AND user_id = %s
            """, [razorpay_order_id, user_id])
            transaction = cursor.fetchone()
            
            if transaction and transaction[0] == 'success':
                return JsonResponse({'success': False, 'error': 'This payment has already been processed'}, status=400)

        # Update transaction record
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE subscription_transactions
                SET razorpay_payment_id = %s, status = 'success', updated_at = %s
                WHERE razorpay_order_id = %s AND user_id = %s
            """, [razorpay_payment_id, datetime.datetime.now(), razorpay_order_id, user_id])

        # Activate subscription
        start_date = datetime.date.today()
        end_date = start_date + datetime.timedelta(days=30)
        credits = {'basic': 10, 'pro': 100, 'premium': 9999}

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE users
                SET plan = %s,
                    remaining_credits = %s,
                    subscription_start_date = %s,
                    subscription_end_date = %s
                WHERE user_id = %s
            """, [plan, credits[plan], start_date, end_date, user_id])
            
            cursor.execute(
            "SELECT email FROM users WHERE user_id=%s",
             [user_id]
            )
            result = cursor.fetchone()

            if result:
                 email = result[0]

            
            subject = "Your MachMate Subscription is Active"
            message = f"""
            Hi,

            Thank you for purchasing the {plan} subscription with MachMate.
            Your subscription is valid for A Month.

            Enjoy all the premium features 🚀

            Regards,
            Team MachMate
            """
            send_mail(subject, message, "noreply@machmate.in", [email], fail_silently=False)


        return JsonResponse({'success': True, 'message': 'Subscription activated!'})
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def cancel_subscription(request):
    """Cancel subscription (end of current period)"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE users
            SET plan = 'none', subscription_end_date = NULL
            WHERE user_id = %s
        """, [user_id])

    return JsonResponse({'success': True, 'message': 'Subscription will be canceled after current period'})


@csrf_exempt
@require_http_methods(["GET"])
def check_credits(request):
    """Check if user has credits available"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT remaining_credits FROM users WHERE user_id = %s", [user_id])
        row = cursor.fetchone()
        has_credits = row[0] > 0 if row else False
    
    
    return JsonResponse({'has_credits': has_credits})
@csrf_exempt
@require_http_methods(["POST"])
def use_credit(request):
    """Use one credit (e.g., when user uploads a quotation)"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)

    try:
        with connection.cursor() as cursor:
            # First check if user has an active subscription with credits
            cursor.execute("""
                SELECT plan, remaining_credits, subscription_end_date 
                FROM users 
                WHERE user_id = %s
            """, [user_id])
            
            user_data = cursor.fetchone()
            
            if not user_data:
                return JsonResponse({'error': 'User not found'}, status=404)
            
            plan, remaining_credits, end_date = user_data
            
            # Check if user has an active subscription
            if plan == 'none' or not end_date:
                return JsonResponse({'success': False, 'error': 'No active subscription found'}, status=400)
            
            # Check if subscription is still valid
            if end_date < datetime.date.today():
                return JsonResponse({'success': False, 'error': 'Subscription has expired'}, status=400)
            
            # Check if user has credits available
            if remaining_credits <= 0:
                return JsonResponse({'success': False, 'error': 'No credits available'}, status=400)
            
            # Deduct one credit
            cursor.execute("""
                UPDATE users
                SET remaining_credits = remaining_credits - 1
                WHERE user_id = %s AND remaining_credits > 0
            """, [user_id])
            
            connection.commit()
            
            # Fetch updated credits
            cursor.execute("SELECT remaining_credits FROM users WHERE user_id = %s", [user_id])
            result = cursor.fetchone()
            
            if result:
                remaining_credits = result[0]
                return JsonResponse({
                    'success': True,
                    'remaining_credits': remaining_credits,
                    'message': 'Credit used successfully'
                })
            else:
                return JsonResponse({'success': False, 'error': 'Failed to deduct credit'}, status=500)
                
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'}, status=500)
