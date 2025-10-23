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

# Updated prices with multiple periods
PRICES = {
    'basic': {
        '1_month': 49900,     # ₹499
        '3_months': 142000,   # ₹1,420
        '6_months': 264000,   # ₹2,640
        '12_months': 479000,  # ₹4,790
    },
    'pro': {
        '1_month': 149900,    # ₹1,499
        '3_months': 427000,   # ₹4,270
        '6_months': 790000,   # ₹7,900
        '12_months': 1439000, # ₹14,390
    },
    'premium': {
        '1_month': 349900,    # ₹3,499
        '3_months': 995000,   # ₹9,950
        '6_months': 1848000,  # ₹18,480
        '12_months': 3359000, # ₹33,590
    }
}

# Credits allocation per plan
CREDITS = {
    'basic': 10,
    'pro': 100,
    'premium': 9999
}

# Period in days
PERIOD_DAYS = {
    '1_month': 30,
    '3_months': 90,
    '6_months': 180,
    '12_months': 365
}


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
        period = data.get('period')
        
        if not plan or not period:
            return JsonResponse({'error': 'Plan and period parameters are required'}, status=400)

        # Validate plan and period
        if plan not in PRICES or period not in PRICES[plan]:
            return JsonResponse({'error': 'Invalid plan or period'}, status=400)

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
                'amount': PRICES[plan][period],
                'currency': 'INR',
                'payment_capture': 1,
                'notes': {
                    'plan': plan,
                    'period': period,
                    'user_id': user_id
                }
            })
        except Exception as e:
            return JsonResponse({'error': f'Razorpay order creation failed: {str(e)}'}, status=500)

        # Save transaction in DB (add period to notes since we don't have a period column)
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO subscription_transactions 
                (user_id, plan, amount, razorpay_order_id, status, created_at)
                VALUES (%s, %s, %s, %s, 'pending', %s)
            """, [user_id, plan, PRICES[plan][period]/100, order['id'], datetime.datetime.now()])

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
        period = data.get('period')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature, plan, period]):
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

        # Calculate subscription dates
        start_date = datetime.date.today()
        days_to_add = PERIOD_DAYS[period]
        
        # Check if user has existing subscription and extend it
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT subscription_end_date, remaining_credits 
                FROM users WHERE user_id = %s
            """, [user_id])
            user_data = cursor.fetchone()
            
            current_end_date = user_data[0] if user_data else None
            current_credits = user_data[1] if user_data else 0
            
            # If user has an active subscription, extend from current end date
            if current_end_date and current_end_date > start_date:
                new_end_date = current_end_date + datetime.timedelta(days=days_to_add)
            else:
                new_end_date = start_date + datetime.timedelta(days=days_to_add)
            
            # Calculate new credits (add monthly credits for the period)
            months_in_period = days_to_add // 30
            new_credits = current_credits + (CREDITS[plan] * months_in_period)

            # Update user subscription
            cursor.execute("""
                UPDATE users
                SET plan = %s,
                    remaining_credits = %s,
                    subscription_start_date = %s,
                    subscription_end_date = %s
                WHERE user_id = %s
            """, [plan, new_credits, start_date, new_end_date, user_id])
            
            # Get user email for notification
            cursor.execute("SELECT email, name FROM users WHERE user_id = %s", [user_id])
            result = cursor.fetchone()
            if result:
                email = result[0]
                name = result[1]

            # Apply pending referral reward
            apply_pending_referral_reward(user_id)
            
            # Send confirmation email
            period_name = period.replace('_', ' ').title()
            subject = f"Your MachMate {plan.title()} Subscription is Active"
            message = f"""
            Hi {name},

            Thank you for purchasing the {plan.title()} subscription with MachMate for {period_name}.
            Your subscription is valid until {new_end_date.strftime('%B %d, %Y')}.

            You now have {new_credits} quotation credits available.

            Plan Details:
            - Plan: {plan.title()}
            - Duration: {period_name}
            - Credits: {new_credits} quotations
            - Valid Until: {new_end_date.strftime('%B %d, %Y')}

            Enjoy all the premium features 🚀

            Regards,
            Team MachMate
            """
            send_mail(subject, message, "noreply@machmate.in", [email], fail_silently=False)

        return JsonResponse({
            'success': True, 
            'message': 'Subscription activated!',
            'end_date': new_end_date.strftime('%Y-%m-%d'),
            'remaining_credits': new_credits
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        # Update transaction status to failed in case of any error
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE subscription_transactions
                SET status = 'failed', updated_at = %s
                WHERE razorpay_order_id = %s AND user_id = %s
            """, [datetime.datetime.now(), razorpay_order_id, user_id])
        
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
            SET plan = 'none', 
                subscription_start_date = NULL,
                subscription_end_date = NULL,
                remaining_credits = 0
            WHERE user_id = %s
        """, [user_id])

    return JsonResponse({'success': True, 'message': 'Subscription cancelled successfully'})


@csrf_exempt
@require_http_methods(["GET"])
def check_credits(request):
    """Check if user has credits available"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT remaining_credits, subscription_end_date 
            FROM users WHERE user_id = %s
        """, [user_id])
        row = cursor.fetchone()
        
        if row:
            remaining_credits = row[0]
            end_date = row[1]
            
            # Check if subscription is still active
            is_active = end_date and end_date >= datetime.date.today()
            has_credits = remaining_credits > 0 and is_active
            
            return JsonResponse({
                'has_credits': has_credits,
                'remaining_credits': remaining_credits,
                'is_active': is_active,
                'end_date': str(end_date) if end_date else None
            })
        
    return JsonResponse({'error': 'User not found'}, status=404)


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


@csrf_exempt
@require_http_methods(["GET"])
def subscription_history(request):
    """Get user's subscription transaction history"""
    user_id = request.session.get("user_id")
    
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT plan, amount, status, created_at, razorpay_order_id, razorpay_payment_id
            FROM subscription_transactions 
            WHERE user_id = %s 
            ORDER BY created_at DESC
        """, [user_id])
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'plan': row[0],
                'amount': float(row[1]),
                'status': row[2],
                'created_at': str(row[3]),
                'order_id': row[4],
                'payment_id': row[5]
            })

    return JsonResponse({'transactions': transactions})


def apply_pending_referral_reward(user_id):
    """Apply referral rewards when user subscribes"""
    with connection.cursor() as cursor:
        # Check if user has pending referral reward
        cursor.execute("""
            SELECT referrer_id FROM referral_rewards 
            WHERE user_id = %s AND applied = 0
        """, [user_id])
        row = cursor.fetchone()
        
        if row:
            referrer_id = row[0]

            # Reward for the new user: +15 days and +10 credits
            cursor.execute("""
                SELECT subscription_end_date, remaining_credits FROM users WHERE user_id=%s
            """, [user_id])
            plan_data = cursor.fetchone()
            
            if plan_data:
                end_date, remaining_credits = plan_data
                if end_date:
                    new_end_date = end_date + datetime.timedelta(days=15)
                else:
                    new_end_date = datetime.date.today() + datetime.timedelta(days=15)

                cursor.execute("""
                    UPDATE users SET 
                        subscription_end_date=%s,
                        remaining_credits=%s
                    WHERE user_id=%s
                """, [new_end_date, remaining_credits + 10, user_id])

            # Reward for the referrer: +15 days and +10 credits
            cursor.execute("""
                SELECT subscription_end_date, remaining_credits FROM users WHERE user_id=%s
            """, [referrer_id])
            ref_data = cursor.fetchone()
            
            if ref_data:
                ref_end_date, ref_credits = ref_data
                if ref_end_date:
                    new_ref_end_date = ref_end_date + datetime.timedelta(days=15)
                else:
                    new_ref_end_date = datetime.date.today() + datetime.timedelta(days=15)

                cursor.execute("""
                    UPDATE users SET 
                        subscription_end_date=%s,
                        remaining_credits=%s
                    WHERE user_id=%s
                """, [new_ref_end_date, ref_credits + 10, referrer_id])

            # Mark referral reward as applied
            cursor.execute("""
                UPDATE referral_rewards SET applied=1 WHERE user_id=%s AND referrer_id=%s
            """, [user_id, referrer_id])