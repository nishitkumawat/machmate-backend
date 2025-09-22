import random
import re
from django.db import connection
from django.contrib.auth.hashers import make_password, check_password
import requests
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.core.mail import send_mail
from django.conf import settings


# ✅ REGISTER VIEW
@api_view(["POST"])
@permission_classes([AllowAny])
def register_view(request):
    name = request.data.get("name")
    email = request.data.get("email")
    password = request.data.get("password")
    phone = request.data.get("phone")
    role = request.data.get("accountType", "buyer")  # default is user

    if not name or not email or not password or not phone:
        return Response({"error": "name, email, phone, and password are required"},
                        status=status.HTTP_400_BAD_REQUEST)

    # ✅ Password validation
    if len(password) < 8:
        return Response({"error": "Password must be at least 8 characters"},
                        status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[A-Z]", password):
        return Response({"error": "Password must contain at least one uppercase"},
                        status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[@$!%*?&]", password):
        return Response({"error": "Password must contain at least one special character (@$!%*?&)"},
                        status=status.HTTP_400_BAD_REQUEST)

    # ✅ Phone validation
    if not re.fullmatch(r"\d{10}", phone):
        return Response({"error": "Phone must be 10 digits"},
                        status=status.HTTP_400_BAD_REQUEST)

    if role not in ["buyer", "maker"]:
        return Response({"error": "Invalid role"},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            # Check if user already exists
            cursor.execute("SELECT user_id FROM users WHERE email=%s OR phone=%s",
                           [ email, phone])
            if cursor.fetchone():
                return Response({"error": "email or phone already exists"},
                                status=status.HTTP_400_BAD_REQUEST)

            # Hash password
            hashed_pw = make_password(password)

            # Insert user
            cursor.execute(
                "INSERT INTO users (name, email, phone, password, role) VALUES (%s, %s, %s, %s, %s)",
                [name, email, phone, hashed_pw, role]
            )

        return Response({"message": "User registered successfully", "role": role},
                        status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    email = request.data.get("email")
    password = request.data.get("password")
    remember_me = request.data.get("remember_me", False)

    if not email or not password:
        return Response({"error": "Please provide email and password"},
                        status=status.HTTP_400_BAD_REQUEST)

    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, password, role FROM users WHERE email=%s", [email])
        user = cursor.fetchone()

        if not user:
            return Response({"error": "Invalid email or password"},
                            status=status.HTTP_401_UNAUTHORIZED)

        user_id, stored_password, role = user

        if not stored_password or not check_password(password, stored_password):
            return Response({"error": "Invalid email or password"},
                            status=status.HTTP_401_UNAUTHORIZED)

        # ✅ Session Handling
        request.session["user_id"] = user_id
        request.session["role"] = role
        request.session.set_expiry(60 * 60 * 24 * 30 if remember_me else 0)

    return Response({
        "message": "Login successful",
        "email": email,
        "role": role
    }, status=status.HTTP_200_OK)

# ✅ LOGOUT VIEW
@api_view(["POST"])
def logout_view(request):
    try:
        request.session.flush()
        return Response({"message": "Logged out successfully"},
                        status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ WHO AM I VIEW
@api_view(["GET"])
def me_view(request):
    user_id = request.session.get("user_id")
    role = request.session.get("role")

    if not user_id:
        return Response({"isAuthenticated": False}, status=status.HTTP_200_OK)

    return Response({
        "isAuthenticated": True,
        "user_id": user_id,
        "role": role
    }, status=status.HTTP_200_OK)

import re
from django.db import connection
from django.contrib.auth.hashers import make_password, check_password
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

# ✅ GET USER PROFILE
@api_view(["GET"])
def get_user_profile(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, name, email, phone, role FROM users WHERE user_id=%s", 
                [user_id]
            )
            user = cursor.fetchone()
            
            if not user:
                return Response({"error": "User not found"}, 
                               status=status.HTTP_404_NOT_FOUND)
            
            # Convert to dictionary
            user_data = {
                "user_id": user[0],
                "name": user[1],
                "email": user[2],
                "phone": user[3],
                "role": user[4]
            }
            
        return Response(user_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ UPDATE USER PROFILE
@api_view(["PUT"])
def update_user_profile(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)
    
    name = request.data.get("name")
    phone = request.data.get("phone")
    current_password = request.data.get("currentPassword")
    new_password = request.data.get("newPassword")
    confirm_password = request.data.get("confirmPassword")
    
    # Validate required fields
    if not name or not phone:
        return Response({"error": "Name and phone are required"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Validate phone format
    if not re.fullmatch(r"\d{10}", phone):
        return Response({"error": "Phone must be 10 digits"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Check if password change is requested
    changing_password = bool(current_password or new_password or confirm_password)
    
    if changing_password:
        if not current_password or not new_password or not confirm_password:
            return Response({"error": "All password fields are required for password change"}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        if new_password != confirm_password:
            return Response({"error": "New passwords do not match"}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        # Password validation
        if len(new_password) < 8:
            return Response({"error": "Password must be at least 8 characters"},
                           status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[A-Z]", new_password):
            return Response({"error": "Password must contain at least one uppercase letter"},
                           status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[@$!%*?&]", new_password):
            return Response({"error": "Password must contain at least one special character (@$!%*?&)"},
                           status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            # Check if phone is already taken by another user
            cursor.execute(
                "SELECT user_id FROM users WHERE phone=%s AND user_id != %s", 
                [phone, user_id]
            )
            if cursor.fetchone():
                return Response({"error": "Phone number already in use"}, 
                               status=status.HTTP_400_BAD_REQUEST)
            
            # Verify current password if changing password
            if changing_password:
                cursor.execute(
                    "SELECT password FROM users WHERE user_id=%s", 
                    [user_id]
                )
                result = cursor.fetchone()
                
                if not result or not check_password(current_password, result[0]):
                    return Response({"error": "Current password is incorrect"}, 
                                   status=status.HTTP_400_BAD_REQUEST)
                
                # Update with password change
                hashed_password = make_password(new_password)
                cursor.execute(
                    "UPDATE users SET name=%s, phone=%s, password=%s WHERE user_id=%s",
                    [name, phone, hashed_password, user_id]
                )
            else:
                # Update without password change
                cursor.execute(
                    "UPDATE users SET name=%s, phone=%s WHERE user_id=%s",
                    [name, phone, user_id]
                )
            
        return Response({"message": "Profile updated successfully"}, 
                       status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ✅ CHANGE PASSWORD ONLY
@api_view(["POST"])
def change_password(request):
    user_id = request.session.get("user_id")
    
    if not user_id:
        return Response({"error": "User not authenticated"}, 
                       status=status.HTTP_401_UNAUTHORIZED)
    
    current_password = request.data.get("currentPassword")
    new_password = request.data.get("newPassword")
    confirm_password = request.data.get("confirmPassword")
    
    if not current_password or not new_password or not confirm_password:
        return Response({"error": "All password fields are required"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    if new_password != confirm_password:
        return Response({"error": "New passwords do not match"}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    # Password validation
    if len(new_password) < 8:
        return Response({"error": "Password must be at least 8 characters"},
                       status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[A-Z]", new_password):
        return Response({"error": "Password must contain at least one uppercase letter"},
                       status=status.HTTP_400_BAD_REQUEST)
    if not re.search(r"[@$!%*?&]", new_password):
        return Response({"error": "Password must contain at least one special character (@$!%*?&)"},
                       status=status.HTTP_400_BAD_REQUEST)

    try:
        with connection.cursor() as cursor:
            # Verify current password
            cursor.execute(
                "SELECT password FROM users WHERE user_id=%s", 
                [user_id]
            )
            result = cursor.fetchone()
            
            if not result or not check_password(current_password, result[0]):
                return Response({"error": "Current password is incorrect"}, 
                               status=status.HTTP_400_BAD_REQUEST)
            
            # Update password
            hashed_password = make_password(new_password)
            cursor.execute(
                "UPDATE users SET password=%s WHERE user_id=%s",
                [hashed_password, user_id]
            )
            
        return Response({"message": "Password changed successfully"}, 
                       status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({"error": str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
import random
import re
import json
from django.db import connection
from django.contrib.auth.hashers import make_password, check_password
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

# ------------------------------
# OTP Storages
# ------------------------------
otp_storage = {}          # Used for signup flow
forgot_otp_storage = {}   # Used for forgot password flow

# ------------------------------
# ------------------------------ Existing Signup OTP FLOW ------------------------------
# ------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
def send_phone_otp(request):
    phone = request.data.get("phone")
    if not phone:
        return Response({"success": False, "message": "Phone is required"}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE phone=%s", [phone])
            if cursor.fetchone():
                return Response({"success": False, "message": "Phone number already exists"}, status=400)

        otp = str(random.randint(100000, 999999))
        otp_storage[phone] = otp
        msg_response = send_sms_otp(phone, otp)
        if msg_response.get("type") == "success":
            return Response({"success": True, "message": "OTP sent successfully"}, status=200)
        else:
            return Response({"success": False, "message": "Failed to send OTP"}, status=500)

    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([AllowAny])
def verify_phone_otp(request):
    phone = request.data.get("phone")
    otp = request.data.get("otp")
    if not phone or not otp:
        return Response({"success": False, "error": "Phone and OTP are required"}, status=400)

    if phone in otp_storage and otp_storage[phone] == otp:
        del otp_storage[phone]
        return Response({"success": True, "message": "Phone verified successfully"}, status=200)
    return Response({"success": False, "error": "Invalid OTP"}, status=400)


@api_view(["POST"])
@permission_classes([AllowAny])
def send_email_otp(request):
    email = request.data.get("email")
    if not email:
        return Response({"success": False, "message": "Email is required"}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE email=%s", [email])
            if cursor.fetchone():
                return Response({"success": False, "message": "Email already exists"}, status=400)

        otp = str(random.randint(100000, 999999))
        otp_storage[email] = otp

        send_mail(
            'Your MachMate Verification Code',
            f'Your OTP for verification is: {otp}',
            'noreply@machmate.com',
            [email],
            fail_silently=False,
        )

        return Response({"success": True, "message": "OTP sent successfully"}, status=200)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([AllowAny])
def verify_email_otp(request):
    email = request.data.get("email")
    otp = request.data.get("otp")
    if not email or not otp:
        return Response({"success": False, "error": "Email and OTP are required"}, status=400)

    if email in otp_storage and otp_storage[email] == otp:
        del otp_storage[email]
        return Response({"success": True, "message": "Email verified successfully"}, status=200)
    return Response({"success": False, "error": "Invalid OTP"}, status=400)


# ------------------------------
# ------------------------------ Forgot Password OTP FLOW ------------------------------
# ------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_send_phone_otp(request):
    phone = request.data.get("phone")
    if not phone:
        return Response({"success": False, "message": "Phone is required"}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE phone=%s", [phone])
            if not cursor.fetchone():
                return Response({"success": False, "message": "Phone number does not exist"}, status=404)

        otp = str(random.randint(100000, 999999))
        forgot_otp_storage[phone] = otp
        
        
        msg_response = send_sms_otp(phone, otp)
        if msg_response.get("type") == "success":
            return Response({"success": True, "message": "OTP sent successfully"}, status=200)
        else:
            return Response({"success": False, "message": "Failed to send OTP"}, status=500)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_verify_phone_otp(request):
    phone = request.data.get("phone")
    otp = request.data.get("otp")
    if not phone or not otp:
        return Response({"success": False, "error": "Phone and OTP are required"}, status=400)

    if phone in forgot_otp_storage and forgot_otp_storage[phone] == otp:
        del forgot_otp_storage[phone]
        return Response({"success": True, "message": "Phone verified successfully"}, status=200)
    return Response({"success": False, "error": "Invalid OTP"}, status=400)


@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_send_email_otp(request):
    email = request.data.get("email")
    if not email:
        return Response({"success": False, "message": "Email is required"}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT user_id FROM users WHERE email=%s", [email])
            if not cursor.fetchone():
                return Response({"success": False, "message": "Email does not exist"}, status=404)

        otp = str(random.randint(100000, 999999))
        forgot_otp_storage[email] = otp

        send_mail(
            'Your MachMate Verification Code',
            f'Your OTP for password reset is: {otp}',
            'noreply@machmate.com',
            [email],
            fail_silently=False,
        )

        return Response({"success": True, "message": "OTP sent successfully"}, status=200)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([AllowAny])
def forgot_verify_email_otp(request):
    email = request.data.get("email")
    otp = request.data.get("otp")
    if not email or not otp:
        return Response({"success": False, "error": "Email and OTP are required"}, status=400)

    if email in forgot_otp_storage and forgot_otp_storage[email] == otp:
        del forgot_otp_storage[email]
        return Response({"success": True, "message": "Email verified successfully"}, status=200)
    return Response({"success": False, "error": "Invalid OTP"}, status=400)


from django.views.decorators.csrf import csrf_exempt

import json, re
from django.http import JsonResponse
from django.contrib.auth.hashers import make_password
from django.views.decorators.csrf import csrf_exempt
from django.db import connection
@csrf_exempt
def reset_password(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get("email")
            phone = data.get("phone")
            new_password = data.get("new_password")

            # ✅ must send either email or phone
            if not new_password or (not email and not phone):
                return JsonResponse({"success": False, "message": "Missing fields"}, status=400)

            # ✅ password validation
            if len(new_password) < 8:
                return JsonResponse({"success": False, "message": "Password must be at least 8 characters"}, status=400)
            if not re.search(r"[A-Z]", new_password):
                return JsonResponse({"success": False, "message": "Password must contain at least one uppercase letter"}, status=400)
            if not re.search(r"[@$!%*?&]", new_password):
                return JsonResponse({"success": False, "message": "Password must contain at least one special character"}, status=400)

            # ✅ hash password
            hashed_password = make_password(new_password)

            # ✅ update DB
            with connection.cursor() as cursor:
                if email:
                    cursor.execute("UPDATE users SET password = %s WHERE email = %s", [hashed_password, email])
                else:
                    cursor.execute("UPDATE users SET password = %s WHERE phone = %s", [hashed_password, phone])

            return JsonResponse({"success": True, "message": "Password reset successful"})

        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)}, status=500)

    return JsonResponse({"success": False, "message": "Invalid request method"}, status=405)


def send_sms_otp(phone, otp):
    """
    Send OTP via MSG91 V5 API
    """
    url = "https://api.msg91.com/api/v5/otp"
    payload = {
        "template_id": settings.MSG91_TEMPLATE_ID,
        "mobile": phone,        # Must include country code, e.g., "91XXXXXXXXXX"
        "otp": otp
    }
    headers = {
        "authkey": settings.MSG91_AUTH_KEY,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    
    try:
        return response.json()
    except Exception:
        return {"error": "Invalid response", "status_code": response.status_code}